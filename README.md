# okf-mcp-server

Reusable, read-only MCP server that exposes a repo's knowledge files (backlog docs, decisions, design notes) as MCP resources over stdio. **Files decide their own fate** via OKF-style frontmatter — no per-source config, no kind/glob registry. One package, one process per owner repo, automatic URI namespacing from the repo basename.

Status: 0.2.0 — frontmatter-driven OKF source format.

## What is this

`okf-mcp-server` ships a configurable MCP server (`Server` from the `mcp` SDK) and a CLI/Python entry point that:

- resolves `owner` from `git rev-parse --show-toplevel` basename (fallback to `cwd` basename with a stderr warning);
- resolves scan roots by precedence: `--roots <csv>` flag → `OKF_MCP_ROOTS` env (colon-separated, PATH-style) → built-in default `[design/, backlog/docs/, backlog/decisions/]`;
- recursively walks every root, parses frontmatter, and registers a file as an MCP resource **iff** `export: true` **and** `type` is non-empty (strict opt-in);
- serves `list_resources` and `read_resource` over stdio for any MCP-aware client (Claude Code, Cursor, etc.).

It is read-only — no `write_resource`, no hot-reload, no search tool.

## Frontmatter contract

Every exported file declares itself in its own frontmatter:

```yaml
---
type: "Architecture Decision"   # required for export; free-form, OKF-semantic; slugified into URI
title: Knowledge Mesh foundation
export: true                    # required; opt-in — absent or false → file is invisible
description: ...                # optional; falls back to first non-heading paragraph (≤ 500 chars)
id: decision-2                  # optional; falls back to filename-derived id
---
```

Fields are read as-is; no schema validation beyond the strict export gate.

## URI scheme

Every resource URI follows `knowledge://{owner}/{type-slug}/{id}`.

- `owner` — basename of the git toplevel (stable contract).
- `type-slug` — deterministic slug of frontmatter `type`: lowercase, non-alphanumeric runs collapsed to `-`, leading/trailing `-` trimmed (`"Architecture Decision"` → `architecture-decision`). **Mutable** — editing `type` changes the slug; consumers must not pin to it.
- `id` — frontmatter `id` if present; otherwise filename-derived: first whitespace-delimited token of the stem (`doc-7 - Partner-...md` → `doc-7`), or the full stem when no whitespace is present (`c8-saas-...-brainstorm.md` → `c8-saas-...-brainstorm`). **Stable** — this is the contract that consumers cite.

Per matched file, the resource carries: `uri`, `name` (frontmatter `title` or filename stem), `description` (frontmatter `description` or first non-heading paragraph, truncated to 500 chars), `mimeType: text/markdown`, and the full body (frontmatter stripped) as content.

## Scan roots

Roots are resolved relative to the **git toplevel**, not cwd. A non-existent root is skipped with a stderr warning, not a fatal error. Files outside any configured root (e.g. `presentations/`, `.git/`) are invisible.

Precedence:

| Source | Separator | Example |
| --- | --- | --- |
| `--roots` flag | `,` | `--roots design/,backlog/docs,backlog/decisions` |
| `OKF_MCP_ROOTS` env | `:` (PATH-style) | `OKF_MCP_ROOTS="design/:backlog/docs:backlog/decisions"` |
| built-in default | n/a | `design/`, `backlog/docs/`, `backlog/decisions/` |

The first non-empty source wins; lower precedence is ignored entirely (not merged).

## In-repo adoption (PEP 723 shim)

When the owner repo lives in the same workspace as this package, the shim resolves `okf-mcp-server` from a local path — no publish step required. One file in the owner repo:

`mcp/server.py`:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["okf-mcp-server"]
#
# [tool.uv.sources]
# okf-mcp-server = { path = "../okf-mcp-server" }
# ///
from okf_mcp_server import run

if __name__ == "__main__":
    run()
```

Run it:

```sh
uv run mcp/server.py
```

`uv` resolves the path source and installs deps on first run. Wire it into Claude Code via a project-level `.mcp.json` entry pointing at `uv run mcp/server.py`.

## Cross-repo adoption

When the owner repo lives in a different repo, install via git URL pinned to a release tag:

```sh
uv add 'okf-mcp-server @ git+https://example.invalid/okf-mcp-server.git@v0.2.0'
```

> The host above is a **placeholder** — replace it with the canonical remote once the repository is published. The package lives at the repository **root** (no `#subdirectory=` is needed). Pin by tag (e.g. `@v0.2.0`) for reproducible federation across owner repos.

The shim then drops the `[tool.uv.sources]` block:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["okf-mcp-server"]
# ///
from okf_mcp_server import run

if __name__ == "__main__":
    run()
```

## Gateway (Streamable HTTP, multi-owner)

Everything above runs the server **per owner over stdio**. The gateway is the
other deployment mode: **one supervised container** that serves *many* owners
over **MCP Streamable HTTP**, so a team points its clients at a single always-on
endpoint instead of spawning a stdio process per repo.

- **Git-sourced, no mounts.** The gateway shallow-clones each owner's repo into a
  container-private cache volume and reuses the exact stdio core (`load_docs` +
  `build_server`) against the checkout. There are no source or consumer mounts.
- **Path-routed allowlist.** Each owner is reachable at `/{owner}/mcp`; the
  `servers.yaml` registry *is* the allowlist — an unregistered owner gets 404.
- **Fresh enough.** Each request pulls the owner if it is staler than its TTL
  (default 60s); `POST /{owner}/refresh` forces an immediate pull.
- **Offline fallback.** The cache volume is authoritative last-good content: when
  an owner already has a healthy checkout and the git source is unreachable (or its
  south token is unset), the gateway serves that **stale-but-good** checkout instead
  of failing empty — at startup and at TTL refresh alike. A good checkout is never
  discarded; only an absent or corrupt one is re-cloned. `GET /status` flags the
  fallback (`source_available:false`, `stale:true`); `POST /{owner}/refresh` returns
  `502` while the owner keeps serving.
- **Auth.** A single shared **north** bearer token guards every route except
  `GET /healthz`; **south** per-host git tokens are injected into clone/fetch
  URLs only and never persisted to `.git/config`.
- **Introspectable.** `GET /config` returns the effective configuration (JSON, or
  `?format=yaml`) from behind the north token — for `credentials` it reports the
  env-var *names* only, never the resolved secret token values.

### `servers.yaml`

The owner allowlist. It holds **no secrets** — `credentials` names the
*environment variable* (`token_env`) that carries each host's token. Mounted
read-only into the container. A committed sample lives at
[`servers.yaml`](servers.yaml):

```yaml
defaults:
  ref: main            # branch/tag checked out when an owner omits its own
  ttl: 60              # per-owner staleness bound (seconds) before the next pull

owners:
  acme:                # reachable at /acme/mcp
    url: https://git.example.invalid/acme/knowledge.git
  beta:
    url: https://bitbucket.example.invalid/beta/knowledge.git
    ref: release       # optional per-owner override of defaults.ref
    ttl: 120           # optional per-owner override of defaults.ttl

credentials:           # per git host; consumed only for authenticated clones
  bitbucket.example.invalid:
    token_env: OKF_GIT_TOKEN_BITBUCKET   # the .env var holding the token
    token_user: x-token-auth             # provider-fixed username
```

### Environment variables

Secrets live in `.env` (copy it from [`.env.example`](.env.example):
`cp .env.example .env`); `.env` is gitignored.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `OKF_GATEWAY_TOKEN` | **yes** | — | North bearer token; the gateway refuses to start without it. |
| `OKF_GIT_TOKEN_*` | as needed | — | South per-host git tokens, referenced by `credentials.token_env` in `servers.yaml`. |
| `OKF_GATEWAY_SERVERS` | no | `servers.yaml` | Path to the registry. |
| `OKF_GATEWAY_CACHE_DIR` | no | XDG cache | Directory for per-owner checkouts. |
| `OKF_GATEWAY_HOST` | no | `0.0.0.0` | Bind host. |
| `OKF_GATEWAY_PORT` | no | `8080` | Bind port. |

### Private CA trust

Owners hosted behind a **private CA** — e.g. a Bitbucket Data Center server
whose HTTPS certificate is signed by a corporate root — fail to clone with
`self-signed certificate in certificate chain`, because that root is absent from
public trust stores. The image provides a build-time drop-in for this: any
PEM-encoded `*.crt` placed in [`certs/`](certs/) is baked into the system trust
bundle (via `update-ca-certificates`), which git uses for HTTPS clones.

```sh
# capture the corporate root (last cert in the presented chain) into the context
openssl s_client -connect git.example.invalid:443 -showcerts </dev/null 2>/dev/null \
  | openssl x509 -outform pem > certs/example-root.crt
docker build -t okf-mcp-gateway .      # the CA is now trusted inside the image
```

`certs/` is **empty by default** (only `.gitkeep`), so a stock build trusts
exactly the public CAs — public-host deployments need do nothing. Real cert
material is gitignored: the reusable image never ships one organization's CA;
each deployer drops their own. See [`certs/README.md`](certs/README.md) for the
full contract (`.crt`/PEM requirement, capturing a chain, verifying it).

### Run it with Docker

Docker is the cross-platform keep-alive (`restart: unless-stopped`) — no
launchd/systemd. Bring it up from the repo root:

```sh
cp .env.example .env          # then set OKF_GATEWAY_TOKEN (and any OKF_GIT_TOKEN_*)
# edit servers.yaml to list your owners
docker compose up -d
```

`docker compose up -d` is **idempotent** — run it again and it is a no-op when the
service is already running, so it doubles as the redeploy command.

> **Manual verification, not an offline gate.** The actual `docker build` /
> `docker compose up -d` — and the idempotent no-op-when-already-running behavior
> — pull base images and clone owner repos over the network, so they are a
> **manual** step. What the automated (offline) gate covers is `docker compose
> config` plus file/content checks (see `tests/test_docker_packaging.py`).

Health and lifecycle:

```sh
curl -fsS http://localhost:8080/healthz               # -> ok (no auth)
curl -X POST http://localhost:8080/acme/refresh \
  -H "Authorization: Bearer $OKF_GATEWAY_TOKEN"        # force a pull (502 if source down)
```

### Inspect the effective config

`GET /config` prints the gateway's **effective** runtime configuration: the
resolved process settings (`servers_path`, `cache_dir`, `host`, `port`,
`auth_required`), the `defaults` block, every owner with its `ref`/`ttl` already
**resolved** against those defaults, and the per-host credential **references**.
It sits behind the north token like every route except `/healthz`, so an
anonymous caller cannot read it. Credentials are reported by **name only** — each
host's `token_env` (the environment-variable name) and `token_user` — so the
resolved secret token value never appears in the output.

Output is JSON by default; `?format=yaml` returns the same structure as YAML. Any
other `format` value is a `400`.

```sh
curl -fsS http://localhost:8080/config \
  -H "Authorization: Bearer $OKF_GATEWAY_TOKEN"        # JSON (default)
curl -fsS "http://localhost:8080/config?format=yaml" \
  -H "Authorization: Bearer $OKF_GATEWAY_TOKEN"        # YAML
```

### Inspect live per-owner status

`GET /status` is the live-runtime sibling of `/config`: where `/config` shows the
static picture, `/status` reports what each owner is **doing right now**. It is a
**pure read** — it never triggers a pull or any other side effect (refreshing is
`POST /{owner}/refresh`'s job) — and it always returns `200`; it is a debugging
view, not a machine health probe (`/healthz` remains the liveness check). Like
every route except `/healthz`, it sits behind the north token.

The body has a top-level `summary` counts block and an `owners` map. Each owner
reports a `state` derived from its runtime:

- **`loading`** — the startup clone is still in flight; `served_commit` is `null`,
  `docs_loaded` is `0`, and `last_pulled_at`/`last_pulled_age_seconds` are `null`.
- **`serving`** — cloned and serving; `served_commit`, `docs_loaded`, an ISO 8601
  UTC `last_pulled_at`, and an integer `last_pulled_age_seconds` are all populated.
  A `serving` owner may be serving a **stale offline fallback** — see the fields
  below.
- **`failed`** — the clone/build failed; an `error` object (`type`, `message`) is
  present and the pull fields are `null`. Any credentials embedded in the error
  message (e.g. a token in a clone URL) are scrubbed before rendering.

Every owner also carries the four **offline-fallback** fields, so a stale
last-good serve is never silent:

- **`source_available`** — whether the most recent git attempt (clone/fetch)
  succeeded. `false` means the owner is serving a **stale offline fallback**: the
  source was unreachable (or its south token unset) and the gateway kept serving
  the last-good checkout rather than failing.
- **`stale`** — derived (`source_available` is `false` with content on hand); the
  quick "am I serving old docs?" flag. A `serving` owner with `stale:true` still
  answers MCP requests — from its persisted checkout, not a fresh pull.
- **`last_pull_attempt_at`** — ISO 8601 UTC of the last pull *attempt* (success or
  failure), distinct from `last_pulled_at` (the age of the served *content*), so
  "serving old docs, still retrying every request" is distinguishable from
  "haven't retried since boot".
- **`last_pull_error`** — the scrubbed error from the last failed attempt (`null`
  after a success); like the `failed` `error`, any token in a URL is redacted.

The owner `url` is deliberately **not** echoed (that is config). Output is JSON by
default; `?format=yaml` returns the same structure as YAML, and any other
`format` value is a `400`.

```json
{
  "summary": { "total": 2, "serving": 1, "loading": 0, "failed": 1 },
  "owners": {
    "acme": {
      "state": "serving", "ref": "main", "served_commit": "1a2b3c4d…",
      "source_available": true, "stale": false,
      "docs_loaded": 42, "last_pulled_at": "2026-07-17T07:46:46Z",
      "last_pulled_age_seconds": 340,
      "last_pull_attempt_at": "2026-07-17T07:46:46Z", "last_pull_error": null
    },
    "beta": {
      "state": "failed", "ref": "release", "served_commit": null,
      "source_available": false, "stale": false,
      "docs_loaded": 0, "last_pulled_at": null, "last_pulled_age_seconds": null,
      "last_pull_attempt_at": "2026-07-17T07:41:12Z",
      "last_pull_error": "fatal: repository not found",
      "error": { "type": "CloneError", "message": "fatal: repository not found" }
    }
  }
}
```

A **stale** owner (source down, healthy checkout) instead looks like `acme` with
`"state": "serving"`, `"source_available": false`, `"stale": true`, its
`served_commit` frozen at the pre-outage SHA, `last_pulled_at` unchanged, and a
fresh `last_pull_attempt_at` on every request until the source returns.

```sh
curl -fsS http://localhost:8080/status \
  -H "Authorization: Bearer $OKF_GATEWAY_TOKEN"        # JSON (default)
curl -fsS "http://localhost:8080/status?format=yaml" \
  -H "Authorization: Bearer $OKF_GATEWAY_TOKEN"        # YAML
```

#### Per-doc artifact inventory: `?artifacts=true`

`served_commit` and `docs_loaded` describe an *owner*; they say nothing about the
individual docs behind it. A consumer handed a bare `knowledge://owner/type/id`
ref therefore cannot tell **what the artifact is** without reading it.
`GET /status?artifacts=true` closes that gap: every owner entry gains an
`artifacts` array with one object per served doc.

| field | meaning |
| --- | --- |
| `uri` | the `knowledge://owner/type-slug/id` ref itself |
| `id` | the doc's stable id (the contract — the slug is not) |
| `type` | the raw frontmatter `type`, e.g. `Architecture Decision` |
| `title` | the doc title |
| `summary` | the doc `description` (declared, or the derived first paragraph) |
| `path` | location **relative to the repo root**, e.g. `design/adr.md` |
| `size` | length of the served content, frontmatter already stripped |
| `content_hash` | the same `sha256:<hex>` each MCP resource carries in `_meta` |

`path` is deliberately repo-relative rather than the absolute checkout path: the
absolute form leaks the gateway's internal filesystem layout and is meaningless
off-box, while the relative one is what a human or a tool can act on in the
source repo.

The array is **opt-in**. Without the parameter — or with `?artifacts=false` —
the payload is exactly as shown above, with no `artifacts` key; `docs_loaded` is
one integer, whereas the inventory grows with an owner's doc count. Any other
value is a `400`, so a typo fails loudly instead of quietly returning nothing. An
owner with no docs on hand (`loading` or `failed`) reports `"artifacts": []`, so
the shape never varies by owner state. Per-doc *freshness* is deliberately absent:
freshness is an owner-level signal (the whole checkout moves together), and the
per-doc change signal is `content_hash` — see the next section.

One owner's entry, abbreviated (the offline-fallback fields are unchanged):

```json
{
  "state": "serving", "ref": "main", "served_commit": "1a2b3c4d…",
  "docs_loaded": 2,
  "artifacts": [
    {
      "uri": "knowledge://acme/architecture-decision/st-adr-1",
      "id": "st-adr-1", "type": "Architecture Decision",
      "title": "Status ADR", "summary": "The status decision body.",
      "path": "design/adr.md", "size": 39,
      "content_hash": "sha256:87204096…"
    }
  ]
}
```

```sh
curl -fsS "http://localhost:8080/status?artifacts=true" \
  -H "Authorization: Bearer $OKF_GATEWAY_TOKEN"
```

#### Offline fallback and `POST /{owner}/refresh`

The persisted cache volume is an **authoritative offline fallback**. If an owner
already has a healthy checkout and the git source is unreachable — or its south
token is unset — the gateway serves that last-good checkout **stale-but-good**
instead of failing empty, both at startup and at each TTL refresh. Only an
**absent or corrupt** checkout with the source down fails the owner; a good
checkout is never discarded (the integrity gate is `git rev-parse HEAD`). An
implicit TTL refresh never breaks an MCP request and self-heals on the next
successful pull, so `GET /{owner}/mcp` keeps serving right through an outage.

An **explicit** `POST /{owner}/refresh`, by contrast, reports the outage loudly:
it returns **`502 Bad Gateway`** — the upstream git source failed, not the gateway
(so not `503`) — with a body naming the still-served commit, while the MCP content
path stays up:

```json
{ "owner": "acme", "served_commit": "1a2b3c4d…", "source_available": false,
  "error": "fatal: unable to access …" }
```

A successful refresh still returns `200` with `{owner, ref, commit, docs_loaded}`.

#### Freshness signals: `served_commit` vs `content_hash`

The gateway exposes two independent freshness signals that answer **different
questions**, so a downstream consumer can verify an upstream's canon is actually
fresh before acting on it:

- **`served_commit`** (owner-level, on `GET /status`) — the git commit SHA of the
  working copy the gateway currently serves for that owner. It is the
  **provenance** signal: it answers *"where did this come from?"*. Because it
  advances after every `POST /{owner}/refresh` that lands a new commit, a consumer
  can confirm a whole merge→push→pull chain ran (e.g. by checking that a known
  merge commit is an ancestor of `served_commit`).
- **`content_hash`** (resource-level, in each MCP resource's `_meta` on both
  `list_resources` and `read_resource`) — a deterministic `sha256:<hex>` digest
  over the served bytes of one exported resource. It is the **content identity**
  signal: it answers *"is this the artifact I need?"*. Byte-identical content
  always yields the same hash regardless of which commit produced it, so a
  consumer can detect a **no-op wake** (the owner's commit moved, but the specific
  artifact it depends on is unchanged → skip re-running) and pin content-addressed
  dependencies.

In short: `served_commit` is *where did this come from*, `content_hash` is *is
this the artifact I need*. The gateway only **exposes** these two signals; the
ancestor check and any cross-project dependency logic live in the consumer.

### Point a consumer at it

A project-level `.mcp.json` entry (Claude Code) using the dual-mode gateway host
resolves both on the host and inside a Ralph devcontainer:
`${MCP_GATEWAY_HOST:-localhost}` is `localhost` on the host and
`host.docker.internal` in the container (which forwards `MCP_GATEWAY_HOST`). This
repo ships exactly this entry as `.mcp.json`:

```json
{
  "mcpServers": {
    "acme-knowledge": {
      "type": "http",
      "url": "http://${MCP_GATEWAY_HOST:-localhost}:8080/acme/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_GATEWAY_TOKEN}"
      }
    }
  }
}
```

Swap `acme` for the owner you want and export `MCP_GATEWAY_TOKEN` in the
consumer's environment, set to the same shared token the gateway runs with (its
`OKF_GATEWAY_TOKEN`).

## Known limitations

- **Single-process per owner.** One running process serves exactly one git repo. Multi-owner federation is achieved by running one shim per owner; there is no built-in aggregator.
- **No hot-reload.** Roots are walked once at startup. Edits to source files require restarting the server.
- **OKF `index.md` / `log.md` are not special.** If they carry `export: true` + `type`, they become ordinary resources; otherwise invisible.
- **`type-slug` is not contractual.** Editing `type` will silently change the URI's middle segment. Cite resources by `id`.

## Linter

A companion CLI, `okf-mcp-lint`, enforces three frontmatter invariants over the same roots the server scans, so misconfigured files fail loud locally and in CI instead of silently disappearing from the served set.

| Check | Severity | Behaviour |
| --- | --- | --- |
| Duplicate `id` within owner | **error** | Non-zero exit; both file paths reported. |
| `export: true` with missing/empty `type` | **error** | Non-zero exit; file path reported. |
| Distinct `type` values that slugify to the same URI segment | **warning** | Zero exit; both type strings + slug reported. |

`id` derivation and `type-slug` derivation are imported directly from the server module (`extract_id`, `slugify_type`) — the linter never reimplements them, so a verdict from the linter implies the same outcome at server load time.

Run it from the owner repo (the `okf-mcp-lint` console script is available once the package is installed):

```sh
okf-mcp-lint
# or, with overrides:
okf-mcp-lint --roots design/,backlog/docs
```

`--roots` and `OKF_MCP_ROOTS` precedence matches the server CLI.

## Tests

Tests live in `tests/`. Run them from the repository root:

```sh
uv run pytest
```

`tests/fixtures/sample-project/` is the worked example used by the smoke / contract / protocol tests; `tests/conftest.py` copies it into a fresh tmp dir and `git init`s it so the resolver behaves as in a real owner repo.
