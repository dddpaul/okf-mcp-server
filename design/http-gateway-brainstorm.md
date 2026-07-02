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
