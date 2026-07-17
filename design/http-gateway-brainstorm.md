# HTTP Streaming Gateway for okf-mcp-server

## Architecture decision

Add a **cross-platform, multi-owner HTTP gateway** as an additive second entry
point (`okf-mcp-gateway`) alongside the existing stdio server. It serves any
number of owner knowledge repos over MCP **Streamable HTTP**, routed by URL
path `/{owner}/mcp`. Owner content is sourced **from git** (corporate Bitbucket
now, GitHub-capable later) — the gateway shallow-clones each repo into an
internal cache volume; there are **no source mounts** and **no consumer-side
mounts**. Lifecycle is managed by **Docker** (`restart: unless-stopped` +
idempotent `docker compose up -d`), deliberately avoiding OS-specific daemons
(launchd/systemd) so the same artifact runs on macOS now and the planned
external Linux knowledge server later.

Chosen option: **Option A — single multi-owner gateway**, git-sourced, Docker-supervised.

## Components / flows

- **Registry** (`servers.yaml`) — maps `owner -> { url, ref, ttl? }` plus a
  per-host `credentials` map. The set of registered owners *is* the north
  allowlist (unregistered owner -> 404).
- **Git manager** (`gateway/git_source.py`) — shallow clone + `fetch --depth 1`
  / `reset --hard <ref>`. Injects the read-only token **in the clone/fetch URL**
  (`https://<token_user>:<token>@host/...`) per-invocation; stored remote is the
  **clean** URL so the token never persists in the cache volume's `.git/config`.
- **Owner cache** (`gateway/owner_cache.py`) — per owner: checkout path, loaded
  `list[ParsedDoc]`, built `Server`, `last_pulled`, `asyncio.Lock`.
  `get_or_refresh(ttl)` = TTL check -> pull -> reuse existing `load_docs` +
  `build_server` verbatim.
- **HTTP app** (`gateway/app.py`) — Starlette: bearer-token auth middleware;
  routes `/{owner}/mcp` (MCP Streamable HTTP handler per owner),
  `POST /{owner}/refresh` (force pull; future webhook target), `GET /healthz`
  (unauthenticated, for Docker healthcheck).
- **Request flow** — auth -> owner lookup -> per-owner lock -> TTL-gated pull +
  reload -> hand off to the owner's MCP handler. Owners are fully independent.
- **Startup** — load registry, background eager-clone of registered owners,
  serve immediately; lazy resolution for any owner whose clone is still in flight.

## Auth (two surfaces)

- **North (consumer -> gateway):** single shared bearer token
  (`OKF_GATEWAY_TOKEN`), checked by one ASGI middleware. Registry = owner
  allowlist. Deferred upgrade: `token -> [owners]` scoping map in the same
  middleware; optional source-IP allowlist.
- **South (gateway -> git host):** per-host read-only HTTP access token, keyed
  by host in `servers.yaml.credentials`:
  ```yaml
  credentials:
    bitbucket.corp:
      token_env: OKF_GIT_TOKEN_BITBUCKET
      token_user: x-token-auth
    github.com:
      token_env: OKF_GIT_TOKEN_GITHUB
      token_user: x-access-token
  ```
  Git manager parses the host from each owner `url`, looks up the credential
  entry, reads the token from `token_env`, and builds
  `https://<token_user>:<token>@host/...`. No matching entry -> unauthenticated
  clone (public repos work). Provider migration = edit the owner's `url` line;
  it auto-selects the matching credential entry. Names are provider-neutral so a
  mixed Bitbucket+GitHub fleet works during migration with zero code change.

## Refresh model

Pull-on-demand + TTL (default ~60s, per-owner overridable). Pull only fires on
an actual request whose owner is staler than its TTL. `POST /{owner}/refresh`
forces an immediate pull and doubles as the Bitbucket/GitHub webhook target once
the gateway is reachable inbound (Linux server phase).

## Scope cuts

- **No stdio changes.** Existing `run()`/`serve_stdio` and the 82 stdio tests
  stay untouched. Purely additive.
- **No per-owner containers** (Option B rejected) — one multi-owner gateway.
- **No off-the-shelf proxy** (Option C rejected: mcp-proxy/supergateway) — keep
  it in-package, one auth choke point.
- **No launchd/systemd dependency** — Docker restart policy only.
- **No live-working-tree serving** — gateway serves committed+pushed state.
- **No per-token owner scoping / IP allowlist in v1** — deferred (drop-in later).
- **No webhook wiring in v1** — the `/refresh` endpoint exists; webhook config
  waits for the inbound-reachable Linux server.

## Open questions

- **CA bundling** — if corp Bitbucket uses an internal CA, bundle it into the
  image and point git at it (`GIT_SSL_CAINFO`). Conditional on host set;
  disappears for public GitHub.
- **Network reachability** — the future external Linux server must reach corp
  Bitbucket (VPN / network allowlist). Environment fact, not a code decision.
- **Bind surface** — default `0.0.0.0:8080` inside the container; decide
  host port-publish vs docker-network-only exposure per environment.

## Hand-off

Next: `ralph-prd` to formalize as PRD, then `ralph-backlog` to generate tasks
(this is multi-task with a shared interface contract — see PRD-fallback below).

## Distilled for ralph-task

**Direction:** Option A — a single cross-platform, multi-owner, git-sourced MCP
**Streamable HTTP** gateway (`okf-mcp-gateway`), additive to the existing stdio
server, Docker-supervised.

**Locked decisions (with rationale):**
- **Additive, not a refactor:** new `gateway/` package; `config.py`/`server.py`/
  `cli.py`/`run()`/`serve_stdio` untouched. *Rationale:* `build_server(docs)` is
  already transport-agnostic, so the core is reused verbatim and stdio keeps working.
- **Single multi-owner gateway, path-routed `/{owner}/mcp`:** *Rationale:* one
  thing to keep alive, any owner reachable, one auth choke point, natural shape
  for the shared Linux knowledge server.
- **Git-sourced content (no mounts):** shallow clone into a gateway-owned cache
  volume. *Rationale:* eliminates consumer- and source-side mounts; matches the
  existing `git+https@tag` federation philosophy; forward-compatible with the
  Linux server.
- **Docker lifecycle (`restart: unless-stopped` + `docker compose up -d`):**
  *Rationale:* cross-platform keep-alive + idempotent start without launchd/systemd;
  same image/compose redeploys to the Linux server.
- **Pull-on-demand + TTL (default 60s), `POST /{owner}/refresh` force + webhook
  target:** *Rationale:* bounded staleness, no inbound-network requirement now,
  cheap; `/refresh` upgrades to a webhook target later with no redesign.
- **North auth = single shared bearer token; registry = owner allowlist:**
  *Rationale:* simplest restriction of consumers; per-token scoping is a drop-in
  upgrade on the same middleware.
- **South auth = per-host token in URL (`https://<token_user>:<token>@host`),
  clean stored remote:** *Rationale:* provider-neutral, supports mixed
  Bitbucket+GitHub fleet during migration with data-only changes; token never
  persists in `.git/config`.
- **`token_user` field name** (not `username`): *Rationale:* it is a fixed
  provider convention (`x-token-auth`/`x-access-token`/`oauth2`), not a personal login.
- **Config format = YAML** (`servers.yaml`): *Rationale:* user preference; PyYAML
  already transitively present, added as explicit dep.

**Scope cuts:**
- No stdio changes; no per-owner containers; no third-party proxy.
- No launchd/systemd; no live-working-tree serving.
- No per-token owner scoping, IP allowlist, or webhook wiring in v1 (all drop-in later).

**Acceptance criteria (sketch):**
- `okf-mcp-gateway` starts from a `servers.yaml`, background-clones registered
  owners, and serves `GET /healthz` 200 immediately.
- `GET/POST /{owner}/mcp` returns 401 without a valid bearer token, 404 for an
  unregistered owner, and serves `list_resources`/`read_resource` for a
  registered owner over MCP Streamable HTTP.
- Content is loaded from a git clone (no source mount); editing+pushing the
  source repo and calling `POST /{owner}/refresh` reflects the change.
- TTL gate: a second request within TTL does not re-pull; after TTL it does.
- Per-host credential resolution builds the authenticated URL from `token_user`
  + `token_env`; the stored git remote contains no credentials.
- Existing 82 stdio tests remain green.
- Ships a `Dockerfile` + `docker-compose.yml` (`restart: unless-stopped`,
  healthcheck, cache volume, `servers.yaml` mount); `docker compose up -d` is idempotent.

**Implementation checklist:**
- `uv add pyyaml starlette uvicorn pydantic`; add `okf-mcp-gateway` script to `pyproject.toml`.
- `gateway/registry.py` — pydantic models for `servers.yaml` (defaults, credentials, owners); validation.
- `gateway/git_source.py` — clone/fetch/reset, per-host auth URL, clean stored remote.
- `gateway/owner_cache.py` — per-owner lock + TTL + reuse `load_docs`/`build_server`.
- `gateway/app.py` — Starlette app, auth middleware, `/{owner}/mcp`, `/{owner}/refresh`, `/healthz`.
- `gateway/__main__.py` — load config, background eager-clone, `uvicorn.run`.
- `Dockerfile` (python-slim + git + uv) and `docker-compose.yml`.
- Tests: registry parse/validate, credential resolution, TTL logic, `GitSource`
  against a `file://` bare-repo fixture, Starlette `TestClient` (401/404/list/read/refresh/healthz).
- README: gateway section (deploy, `servers.yaml`, env vars, consumer `.mcp.json`).

---

## Addendum: GET /status live-runtime endpoint (added 2026-07-17)

### Why
The gateway now ships `GET /config` (TASK-11), which prints the *effective
configuration* — the static picture of what the gateway is set up to serve. It
says nothing about what each owner is *doing right now*: is a clone still in
flight, is an owner serving, did one fail, how stale is its content? Ops needs a
single-curl live view to answer "what's each owner doing right now" during
debugging. All of this state already lives in `OwnerState`/`OwnerCache`; the
endpoint is almost entirely an additive read.

### What changed
Add a global, bearer-gated, read-only `GET /status` endpoint, a sibling of
`/config` (always 200, rich detail, human/ops audience). It is a **pure read**:
it reports current in-memory state and never triggers a TTL pull or any side
effect.

**Response shape** (default JSON; `?format=yaml` switches to YAML exactly like
`/config`; an unsupported `?format=` value → 400):

```json
{
  "summary": { "total": 3, "serving": 2, "loading": 0, "failed": 1 },
  "owners": {
    "acme": {
      "state": "serving",
      "ref": "main",
      "commit": "1a2b3c4d…",
      "docs_loaded": 42,
      "last_pulled_at": "2026-07-17T07:46:46Z",
      "last_pulled_age_seconds": 340
    },
    "beta": {
      "state": "failed",
      "ref": "release",
      "commit": null,
      "docs_loaded": 0,
      "last_pulled_at": null,
      "last_pulled_age_seconds": null,
      "error": { "type": "CloneError", "message": "fatal: repository not found (bitbucket.corp)" }
    }
  }
}
```

**Per-owner `state`** is derived from the existing `OwnerState` — no new flags:
`ready` unset → `"loading"`; `ready` set + `session_manager` present →
`"serving"`; `ready` set + `session_manager` is `None` → `"failed"` (with
`error` populated). The `error` key is present **only** for `failed`. `url` is
deliberately **not** echoed (that's config, and it keeps a redaction surface off
this endpoint). `commit`/`docs_loaded`/`last_pulled_*` are `null`/`0` while
`loading` — the honest representation of an owner with no content yet.

**Two-clock addition to `OwnerCache`** (the only change outside `app.py`,
purely additive so US-003 TTL tests stay green): keep the existing injectable
`clock` **monotonic** for TTL correctness (immune to wall-clock/NTP jumps), and
add a second injectable `wall_clock: Callable[[], float] = time.time` plus a
`last_pulled_wall: float | None` field, stamped in `_apply` alongside the
existing `last_pulled`. `/status` renders `last_pulled_at` (ISO 8601 UTC) from
the wall stamp and `last_pulled_age_seconds` from `int(cache._clock() -
cache.last_pulled)` — same monotonic source as TTL, so age is consistent.

**Security — render-time credential scrub (Option A).** The south git auth
injects the token into the clone URL (`https://x-token-auth:<TOKEN>@host/…`), so
a clone-failure exception can carry the token. A small pure helper
`_scrub_credentials(text)` in `app.py` redacts URL userinfo
(`(?P<scheme>https?://)[^/@\s]+@` → `\g<scheme>***@`) — host/path survive for
debugging, the `user:token` pair is gone. Applied only to the failed-owner
`error.message`; `type(err).__name__` passes through raw. The scrub lives only
on the status render path (not exported); a future endpoint surfacing
`state.error` must re-apply it.

### Implementation checklist
- `owner_cache.py`: add `wall_clock` param (default `time.time`), add
  `last_pulled_wall: float | None = None` field, stamp it in `_apply` — three
  additive spots, no behavior change.
- `app.py`: add `_owner_status(owners)` helper (sibling of `_effective_config`)
  building the `summary` + `owners` maps; add `_scrub_credentials(text)` helper;
  add an async `status` route reusing the `/config` `?format=` + 400 handling;
  register `Route("/status", status, methods=["GET"])` right after `/config`.
- `README.md`: document `GET /status`, the state enum, the fields, and
  `?format=`, next to the `/config` docs.
- `tests/test_gateway_status.py`: TestClient + `file://` bare-repo fixtures —
  happy path (serving, fixed wall clock → exact ISO, advanced monotonic clock →
  exact `age_seconds`, summary counts); failed owner (state/error/nulls +
  token-never-leaks guard in JSON and YAML); loading state returns immediately
  without blocking; `?format=yaml` round-trip; `?format=xml` → 400; bearer
  401/200; `/healthz` stays open.
- Confirm the existing 82 stdio tests and all gateway tests stay green.

### Distilled for ralph-task

**Direction:** Option A — add a global, bearer-gated, read-only `GET /status`
endpoint (JSON default, `?format=yaml`), rendering live per-owner runtime state
with render-time credential scrubbing; minimal and additive, mirroring `/config`.

**Locked decisions (with rationale):**
- **Global `GET /status`, one call lists all owners.** *Rationale:* the audience
  is ops wanting an at-a-glance view of every owner at once.
- **Human/ops audience — always 200, rich detail, behind the north bearer token
  (not `/healthz`-open).** *Rationale:* it's a debugging view, not a machine
  health probe; the middleware already gates every route but `/healthz`.
- **Pure read — never triggers a pull or any side effect.** *Rationale:* status
  observes current state; refreshing is `/{owner}/refresh`'s job.
- **State enum derived from existing `OwnerState`** (`loading`/`serving`/
  `failed`). *Rationale:* no new flags; the readiness/session_manager/error
  fields already encode it.
- **Two clocks in `OwnerCache`: monotonic for TTL, new injectable wall clock for
  display.** *Rationale:* TTL must stay monotonic (jump-immune); humans need an
  absolute timestamp; both injectable keeps tests deterministic.
- **Report both `last_pulled_at` (ISO 8601 UTC) and `last_pulled_age_seconds`.**
  *Rationale:* timestamp for humans, age for quick "is it stale" scanning.
- **Render-time credential scrub (Option A), applied only to the failed-owner
  error message.** *Rationale:* a clone-failure exception can embed the south
  git token in the URL; scrubbing at render keeps the change minimal and off the
  already-reviewed `git_source`.
- **Include a top-level `summary` counts block.** *Rationale:* at-a-glance totals
  are the point of a global status view.
- **Match `/config` format handling** (`?format=` query param, YAML via
  `application/yaml`, unsupported value → 400). *Rationale:* one consistent
  surface across the two introspection endpoints.

**Scope cuts:**
- No per-owner `GET /{owner}/status` route (global only).
- No machine-monitoring semantics — status is always 200, never reflects health
  in the HTTP status code; `/healthz` remains the liveness probe.
- Do **not** echo owner `url` in the status body.
- No source-level (git_source) scrubbing — render-time only (Option A, not B/C).
- No change to TTL/refresh behavior; `owner_cache.py` edits are additive only.

**Acceptance criteria (sketch):**
- `GET /status` returns 200 JSON with top-level `summary` and `owners`; each
  owner shows `state`, `ref`, `commit`, `docs_loaded`, `last_pulled_at`,
  `last_pulled_age_seconds`.
- `summary` reports `total`/`serving`/`loading`/`failed` matching the owners map.
- A serving owner shows `state:"serving"`, non-null `commit`, `docs_loaded`
  matching its fixture, an ISO `last_pulled_at`, and an integer
  `last_pulled_age_seconds`; with a fixed wall clock the ISO string is exact and
  advancing the monotonic clock by N yields `last_pulled_age_seconds == N`.
- A failed owner shows `state:"failed"`, an `error` object with `type` and a
  scrubbed `message`, and null `commit`/`last_pulled_*`; it is counted in
  `summary.failed`.
- When an owner's clone fails with a token-bearing URL in the exception, the
  token string appears nowhere in the `/status` response (JSON and YAML).
- A still-cloning owner shows `state:"loading"` and `/status` returns without
  blocking on its readiness.
- `GET /status?format=yaml` returns 200 `application/yaml` that `yaml.safe_load`
  round-trips to the JSON structure; an unsupported `?format=` value → 400.
- `/status` requires the bearer token (missing/wrong → 401, correct → 200);
  `GET /healthz` stays open.
- The existing 82 stdio tests remain green and their files are unchanged; lint
  (`uv run mypy . && uv run ruff check .`) and `uv run pytest` pass.

**Implementation checklist:**
- `owner_cache.py`: add injectable `wall_clock` (default `time.time`), add
  `last_pulled_wall: float | None` field, stamp it in `_apply`.
- `app.py`: add `_owner_status(owners)` + `_scrub_credentials(text)` helpers;
  add the `status` route (reusing `/config` `?format=`/400 handling); register
  `Route("/status", …)` after `/config`.
- `README.md`: document `GET /status`, the state enum, fields, and `?format=`.
- `tests/test_gateway_status.py`: happy/failed/loading, token-leak guard,
  `?format=` round-trip + 400, bearer 401/200, `/healthz` open.
