# PRD: HTTP Streaming Gateway for okf-mcp-server

## Introduction

Today `okf-mcp-server` serves one owner repo's knowledge docs over MCP **stdio**.
That works when the consumer and the docs share a filesystem, but it does not
work for a **devcontainer** that should reach knowledge over the network without
mounting the source folder.

This feature adds an **additive** second entry point, `okf-mcp-gateway`: a
single, cross-platform, **multi-owner** server that exposes knowledge over MCP
**Streamable HTTP** at `/{owner}/mcp`. Owner content is sourced **from git**
(corporate Bitbucket now, GitHub-ready later): the gateway shallow-clones each
registered repo into a gateway-owned cache volume — **no source mounts and no
consumer-side mounts**. Lifecycle is managed by **Docker**
(`restart: unless-stopped` + idempotent `docker compose up -d`), avoiding
OS-specific daemons so the same artifact runs on macOS now and the planned
external Linux knowledge server later.

The full design rationale lives in `design/http-gateway-brainstorm.md`. This PRD
slices it into implementable, independently verifiable user stories.

## Goals

- Serve any number of owner repos over MCP Streamable HTTP from one process,
  routed by URL path `/{owner}/mcp`.
- Source content from git (shallow clone into a gateway-owned cache); zero mounts.
- Restrict consumers with a shared bearer token; treat the registry as the owner
  allowlist (unregistered owner → 404).
- Authenticate to git hosts with per-host tokens using a provider-neutral scheme
  so a Bitbucket→GitHub migration is a data-only change.
- Keep the gateway alive and idempotently startable cross-platform via Docker.
- Leave the existing stdio server and its 82 tests **completely untouched**.

## User Stories

Stories are ordered as a **thin vertical slice first**, then successive
deepening. Each is small enough for one focused session. Every AC is verifiable
**offline** — via `file://` bare-repo git fixtures + Starlette `TestClient`,
with no live Bitbucket, network, or secrets (the autonomous Ralph loop cannot
reach corp Bitbucket). Project quality gate for every story:
`uv run mypy . && uv run ruff check .` and `uv run pytest`.

### US-001: Vertical slice — serve one git-sourced owner over Streamable HTTP
**Description:** As a devcontainer consumer, I want a single owner's docs served
over MCP Streamable HTTP, sourced from a git clone, so I can read knowledge over
the network without mounting the folder.

**Acceptance Criteria:**
- [ ] New `okf_mcp_server/gateway/` package and `okf-mcp-gateway` console script
      (added to `pyproject.toml`); existing `run()`/`serve_stdio`/`cli.py` unchanged.
- [ ] Given one owner (name + git URL + ref via minimal config/env), the gateway
      shallow-clones the repo into a cache directory and loads docs by reusing
      the existing `load_docs` and `build_server` **verbatim** (no fork/copy).
- [ ] `GET /healthz` returns 200 as soon as the app is up.
- [ ] An MCP Streamable HTTP client (Starlette `TestClient`) can `list_resources`
      and `read_resource` for that owner at `/{owner}/mcp`, returning the same
      docs the stdio server would.
- [ ] Content demonstrably comes from a git clone of a `file://` bare-repo
      fixture, not from a mounted/working-tree path.
- [ ] Existing 82 stdio tests remain green; mypy + ruff clean.

### US-002: Registry (`servers.yaml`), multi-owner routing, owner allowlist
**Description:** As an operator, I want to declare owners in one YAML file so the
gateway serves each at `/{owner}/mcp` and rejects unregistered owners.

**Acceptance Criteria:**
- [ ] `gateway/registry.py` parses `servers.yaml` into validated pydantic models:
      `defaults` (`ref`, `ttl`), `owners` (`{owner: {url, ref?, ttl?}}`), and a
      `credentials` section (parsed and validated; consumed in US-004).
- [ ] Two distinct owners are served independently, each at its own
      `/{owner}/mcp`; a request to an **unregistered** owner returns **404**.
- [ ] Registered owners are eager-cloned in the background at startup; an owner
      whose clone is still in flight resolves lazily on first request without
      blocking other owners or `/healthz`.
- [ ] A malformed or missing `servers.yaml` fails fast at startup with a clear,
      actionable error message.
- [ ] Unit tests cover registry parsing, defaults merging, and validation errors.
- [ ] mypy + ruff clean; stdio tests green.

### US-003: Pull-on-demand TTL cache + `POST /{owner}/refresh`
**Description:** As an operator, I want the gateway to serve reasonably fresh
committed content without re-pulling on every request, plus a way to force a pull.

**Acceptance Criteria:**
- [ ] `gateway/owner_cache.py` holds per-owner state (checkout path, loaded docs,
      built `Server`, `last_pulled`, `asyncio.Lock`) and a `get_or_refresh(ttl)`
      that: if staler than TTL, `fetch --depth 1` + `reset --hard <ref>`, and on a
      changed tree re-runs `load_docs` and rebuilds the owner's `Server`.
- [ ] With a `file://` fixture: after committing a change to the source, a request
      **within** TTL does not re-pull (served content unchanged); a request
      **after** TTL reflects the change. TTL/clock is injectable for deterministic tests.
- [ ] `POST /{owner}/refresh` forces an immediate pull regardless of TTL and
      returns a JSON summary (`owner`, `ref`, `commit`, `docs_loaded`).
- [ ] The per-owner lock prevents concurrent double-pulls (verified with a spy /
      concurrent-request test); a pull on one owner never blocks another owner.
- [ ] mypy + ruff clean; stdio tests green.

### US-004: North bearer auth + south per-host git credentials
**Description:** As an operator, I want to require a bearer token from consumers
and authenticate the gateway to git hosts with per-host tokens, in a
provider-neutral way.

**Acceptance Criteria:**
- [ ] One ASGI auth middleware: requests to `/{owner}/mcp` and `/{owner}/refresh`
      require `Authorization: Bearer <OKF_GATEWAY_TOKEN>` → **401** if missing or
      wrong; `GET /healthz` is exempt (open).
- [ ] `gateway/git_source.py` resolves credentials per **git host**: parse host
      from the owner `url`, look up the matching `credentials[host]` entry, read
      the token from its `token_env`, and build the authenticated clone/fetch URL
      `https://<token_user>:<token>@host/...`. No matching entry → unauthenticated
      clone (public repos work).
- [ ] The **stored** git remote in the cache checkout contains **no credentials**
      (token injected per-invocation only); verifiable by inspecting the fixture
      checkout's `.git/config`.
- [ ] Unit test: given `token_user` + a token env var, the URL builder produces
      the exact expected authenticated URL; and given no credential entry,
      produces the clean URL. (No live authenticated host needed.)
- [ ] mypy + ruff clean; stdio tests green.

### US-005: Docker packaging, compose, and README
**Description:** As an operator, I want to run the gateway as a supervised
container and know how to point a devcontainer at it.

**Acceptance Criteria:**
- [ ] `Dockerfile` (python-slim base + `git` + `uv`) installs the package and runs
      `okf-mcp-gateway`.
- [ ] `docker-compose.yml`: `restart: unless-stopped`; publishes `8080:8080`;
      `env_file: .env` (`OKF_GATEWAY_TOKEN`, `OKF_GIT_TOKEN_*`); a named cache
      volume for checkouts; `servers.yaml` mounted read-only; a `healthcheck`
      hitting `/healthz`.
- [ ] `docker compose config` validates the compose file (offline, gating AC);
      actual `docker build` / `up -d` documented as a manual verification step.
- [ ] README gains a "Gateway" section: what it is, `servers.yaml` example, env
      vars, `docker compose up -d` (noting idempotency), and a consumer `.mcp.json`
      snippet pointing at `http://host.docker.internal:8080/{owner}/mcp` with the
      bearer token.
- [ ] `.env.example` and a sample `servers.yaml` are committed (no secrets).
- [ ] mypy + ruff clean; stdio tests green.

## Functional Requirements

- **FR-1:** The gateway MUST expose an MCP **Streamable HTTP** endpoint per owner
  at `/{owner}/mcp`, reusing the existing `load_docs` and `build_server`.
- **FR-2:** The gateway MUST source each owner's content by shallow-cloning its
  git repo into a gateway-owned cache; it MUST NOT require any source mount or
  consumer-side mount.
- **FR-3:** The gateway MUST read owners and per-host credentials from a single
  `servers.yaml`; the set of registered owners is the authoritative allowlist.
- **FR-4:** A request for an unregistered owner MUST return 404.
- **FR-5:** All authenticated routes MUST require a valid `Authorization: Bearer`
  token equal to `OKF_GATEWAY_TOKEN`; otherwise 401. `GET /healthz` MUST be open.
- **FR-6:** For git auth, the gateway MUST resolve a per-host token via
  `credentials[host].token_env` and inject it into the clone/fetch URL as
  `https://<token_user>:<token>@host/...`; it MUST NOT persist credentials in the
  stored git remote.
- **FR-7:** The gateway MUST serve committed+pushed content and refresh via
  pull-on-demand gated by a per-owner TTL (default 60s, per-owner overridable).
- **FR-8:** `POST /{owner}/refresh` MUST force an immediate pull and reload,
  independent of TTL, and return a JSON summary.
- **FR-9:** Per-owner operations MUST be serialized by an async lock so concurrent
  requests never trigger a double-pull; owners MUST be mutually independent.
- **FR-10:** The gateway MUST start eager background clones for registered owners
  and MUST begin serving `/healthz` immediately regardless of clone progress.
- **FR-11:** The project MUST ship a `Dockerfile` and `docker-compose.yml`
  (`restart: unless-stopped`, healthcheck, cache volume, `servers.yaml` mount,
  `8080:8080` publish) supporting idempotent `docker compose up -d`.
- **FR-12:** The existing stdio entry point (`run()`/`serve_stdio`/`cli.py`) and
  its 82 tests MUST remain unchanged and green.

## Non-Goals (Out of Scope)

- **Live-working-tree serving** — the gateway serves committed+pushed state only.
- **Per-owner containers** — one multi-owner gateway (Option B rejected).
- **Third-party MCP proxy** (mcp-proxy/supergateway) — kept in-package (Option C rejected).
- **launchd/systemd supervision** — Docker restart policy only.
- **Per-token owner scoping** and **source-IP allowlist** — deferred; the auth
  middleware is the drop-in point later.
- **Git webhook wiring** — `POST /{owner}/refresh` exists and is webhook-shaped,
  but no webhook is configured in v1 (waits for the inbound-reachable Linux server).
- **Internal-CA bundling** — deferred/conditional; only needed if a registered
  host uses a private CA. Not implemented in v1.
- **A live-Bitbucket integration test** — un-runnable offline; real-host checks
  are manual post-merge notes, never gating ACs.

## Technical Considerations

- **New deps:** `pyyaml` (explicit; already transitively present via
  `python-frontmatter`), `starlette`, `uvicorn`, `pydantic`. Add via `uv add`.
- **Reuse, don't fork:** `load_docs`, `build_server`, `slugify_type`, `extract_id`
  are used verbatim; the gateway only wraps them (git management, per-owner cache,
  routing, auth).
- **Streamable HTTP lifecycle:** each owner's MCP session manager must run within
  the Starlette app **lifespan**; per-owner handlers are mounted under
  `/{owner}/mcp`.
- **git invocation:** shell out to `git` via `subprocess`, mirroring the existing
  `config._git_toplevel` pattern; `--depth 1` clones/fetches; `reset --hard <ref>`
  handles force-pushes.
- **Provider-neutral credentials:** `credentials` keyed by host with `token_env`
  + `token_user` (e.g. `x-token-auth` for Bitbucket, `x-access-token` for GitHub);
  migrating an owner is editing its `url` line only.
- **Test infrastructure:** extend the `conftest.py` git-init pattern to build
  `file://` **bare** repos as clone sources; use Starlette `TestClient` for HTTP.
- **Config file format:** YAML (`servers.yaml`), per user preference.

## Success Metrics

- A devcontainer reads a registered owner's knowledge over
  `http://host.docker.internal:8080/{owner}/mcp` with a bearer token — no mount.
- Adding a new owner is a one-line `servers.yaml` edit (plus a per-host token once).
- Migrating an owner Bitbucket→GitHub is a data-only `url` change, no code edit.
- `docker compose up -d` is a no-op when the gateway is already running.
- Zero regressions: 82 stdio tests still pass.

## Open Questions

- **Bind surface:** default `0.0.0.0:8080` in-container + `8080:8080` publish is
  chosen for the Mac devcontainer; revisit docker-network-only exposure on the
  Linux server.
- **CA bundling** mechanism if/when a corp host needs a private CA
  (`GIT_SSL_CAINFO` + baked cert) — deferred until required.
- **Corp network reachability** from the future external Linux server (VPN /
  allowlist) — an environment fact to resolve at deploy time, not in code.

## Next Step

Convert to backlog tasks:

```
Load the ralph-backlog skill and convert design/http-gateway-prd.md to backlog tasks
```
