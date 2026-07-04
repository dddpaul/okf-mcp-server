# Feature Review: http-gateway (post-implementation, cumulative)

**Date:** 2026-07-03
**Type:** Post-implementation cumulative cross-task review of merged code.
**Scope:** TASK-4 → TASK-5 → TASK-6 → TASK-7 → TASK-8 (all Done, merged to local `master`).
**Diff range:** `0e83a2348ef91da432a6acbcb7ce9089423ed760..HEAD` (~3055 insertions, 28 files).

**Verdict: Aligned**

**Passes run:** 1 (PRD Coverage), 2 (Non-Goal Protection), 3 (Brainstorm Scope Cuts), 4 (Success-Metric Realism), 5 (Out-of-Scope Creep).
**Passes skipped:** None. Both `design/http-gateway-prd.md` and `design/http-gateway-brainstorm.md` exist; the PRD has Non-Goals and Success Metrics; the brainstorm has an explicit Scope Cuts section. No `.claude/ralph-review-rules.md` present, so the standard rubric applies.

All quality gates independently re-verified: `uv run mypy .` → "no issues found in 26 source files"; `uv run ruff check .` → "All checks passed!"; the 82 stdio tests (`test_config/test_server/test_contract/test_protocol/test_smoke/test_linter`) pass unmodified; the stdio source surface (`config.py`, `server.py`, `cli.py`, package `__init__.py`) is byte-for-byte untouched in the diff. The full gateway suite passes except one environment-only failure discussed in the Drift List.

---

## Intent → Implementation Matrix

### User Stories

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| US-001 | Vertical slice: one git-sourced owner over Streamable HTTP; reuse `load_docs`/`build_server` verbatim; `/healthz` 200; content from a `file://` clone not a mount | Delivered | `owner_cache.py:224-227` reuses `load_docs` verbatim via `ServerConfig(owner, roots=(checkout,))`; `app.py:104` wraps `build_server` output in `StreamableHTTPSessionManager`; `test_gateway.py:180-207` proves content originates from a clone in the cache dir (checkout `!= work_dir`/`bare_dir`, origin == `file://` URL) |
| US-002 | Registry parse (defaults/owners/credentials); two owners routed independently; unregistered → 404; eager bg clone + lazy resolve; malformed yaml fails fast | Delivered | `registry.py:108-194` pydantic models + `load_registry` fail-fast; `app.py:257-268` per-owner background clone tasks; `app.py:125-143` `_MCPRouter` 404/await-ready dispatch; `test_gateway.py:138-166` two owners; `:168-177` 404; `:210-257` slow owner doesn't block healthz/others |
| US-003 | Per-owner TTL cache; within-TTL no re-pull, after-TTL reflects change; `POST /{owner}/refresh` JSON summary; per-owner lock prevents double-pull, cross-owner independent | Delivered | `owner_cache.py:127-173` `get_or_refresh`/`force_refresh` with double-checked `asyncio.Lock`; `app.py:231-255` refresh endpoint returns `{owner,ref,commit,docs_loaded}`; `test_owner_cache.py:186-224` spy proves single fetch under concurrency; `:228-275` cross-owner non-blocking |
| US-004 | ASGI bearer middleware (401 missing/wrong, `/healthz` open); per-host credential URL builder; clean stored remote; URL-builder unit test both cases | Delivered | `app.py:146-185` `BearerAuthMiddleware` with `secrets.compare_digest`; `git_source.py:44-87` `build_authenticated_url`; `:163-165` resets origin to clean URL; `test_git_source_auth.py:32-58,91-112,176-187` cover both branches + `.git/config` has no `@` |
| US-005 | Dockerfile (slim+git+uv, runs console script); compose (restart/8080/env_file/named volume/ro mount/healthcheck); `docker compose config` gate; README section; `.env.example` + sample `servers.yaml` no secrets | Delivered | `Dockerfile` python:3.14-slim, non-root uid 10001, `CMD ["okf-mcp-gateway"]`; `docker-compose.yml` all six properties present; `README.md:109-216` full section incl. `.mcp.json` at `host.docker.internal:8080`; `test_docker_packaging.py` 11 offline checks |

### Functional Requirements

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| FR-1 | Streamable HTTP per owner at `/{owner}/mcp`, reusing `load_docs`/`build_server` | Delivered | `app.py:277` route; `owner_cache.py:196,222,227` reuse |
| FR-2 | Shallow clone into gateway-owned cache; no mounts | Delivered | `git_source.py:159-160` `git clone --depth 1`; `test_gateway.py:117-135` shallow (`rev-list --count == 1`) |
| FR-3 | Owners + credentials from single `servers.yaml`; registered set = allowlist | Delivered | `registry.py` whole module; allowlist enforced at `app.py:127-132` |
| FR-4 | Unregistered owner → 404 | Delivered | `app.py:128-132` (mcp), `:233-237` (refresh); `test_gateway.py:168-177`, `:326-343` |
| FR-5 | Bearer token on authed routes → 401; `/healthz` open | Delivered | `app.py:163-175`; `test_gateway.py:346-391` |
| FR-6 | Per-host token via `credentials[host].token_env` injected as `https://<user>:<token>@host/...`; no creds in stored remote | Delivered | `git_source.py:69-87`, `:163-165`; `test_git_source_auth.py:91-112,176-187` |
| FR-7 | Committed content, pull-on-demand gated by per-owner TTL (default 60s, overridable) | Delivered | `owner_cache.py:142-152`; default 60s pinned by `test_registry.py:86-96`; override by `test_owner_cache.py:87-112` |
| FR-8 | `POST /{owner}/refresh` forces pull independent of TTL, returns JSON | Delivered | `owner_cache.py:154-173`, `app.py:231-255`; `test_gateway.py:292-323`, `test_owner_cache.py:161-183` |
| FR-9 | Per-owner async lock serializes pulls; owners independent | Delivered | `owner_cache.py:110,145-152`; `test_owner_cache.py:186-275` |
| FR-10 | Eager background clones; `/healthz` serves immediately regardless of clone progress | Delivered | `app.py:257-268` lifespan tasks; `/healthz` route has no readiness gate; `test_gateway.py:210-257` |
| FR-11 | Ships Dockerfile + compose (restart/healthcheck/cache volume/servers.yaml mount/8080), idempotent `up -d` | Delivered | `Dockerfile`, `docker-compose.yml`; idempotency documented (`README.md:184-197`) — documented, not offline-tested, which the PRD explicitly permits |
| FR-12 | stdio entry point + 82 tests unchanged and green | Delivered | `git diff --stat` shows zero changes to stdio source/tests; re-ran: `82 passed` |

---

## Non-Goal Violations — None detected

Each of the 8 non-goals/scope-cuts checked against the code:

- **Live-working-tree serving** — not present; `owner_cache.py` always serves a `git clone` checkout, `fetch_and_reset` resets to `FETCH_HEAD`.
- **Per-owner containers** — single `Starlette` app with a `dict[str, OwnerState]`; one Dockerfile/compose service.
- **Third-party MCP proxy** — no mcp-proxy/supergateway; only `starlette`/`uvicorn`/`pydantic`/`pyyaml` added.
- **launchd/systemd** — nothing beyond `restart: unless-stopped` in compose.
- **Per-token owner scoping / IP allowlist** — `BearerAuthMiddleware` uses one shared token with no per-owner scope map or IP check (drop-in point preserved).
- **Git webhook wiring** — `/refresh` endpoint exists but no webhook config anywhere.
- **Internal-CA bundling** — no `GIT_SSL_CAINFO` or baked cert (Dockerfile installs only `ca-certificates`).
- **Live-Bitbucket integration test** — every test is offline against `file://` fixtures; no network host contacted.

## Scope Cut Violations — None detected

The brainstorm's "Distilled for ralph-task" locked decisions are honored exactly, including the two most-specific: `token_user` field name is used (not `username`) — `registry.py:88`; config format is YAML — `registry.py:168` `yaml.safe_load`.

---

## Success Metric Assessment

| Metric | Status | Notes |
|--------|--------|-------|
| Devcontainer reads a registered owner over `http://host.docker.internal:8080/{owner}/mcp` with a bearer token, no mount | Measurable post-merge | End-to-end HTTP-over-ASGI path (list/read with bearer) exercised in-process by `test_gateway.py:412-436`; the literal `host.docker.internal` hop is a deploy-time fact, left to the documented manual step |
| Adding a new owner is a one-line `servers.yaml` edit | Measurable | `registry.py` requires only `{owner: {url}}`; `test_gateway_main.py:60-82` builds an app from a one-owner file |
| Bitbucket→GitHub migration is a data-only `url` change | Measurable (by construction) | `build_authenticated_url` keys purely off the URL host (`git_source.py:70-73`); `test_git_source_auth.py` shows host-driven selection with no per-provider code path |
| `docker compose up -d` is a no-op when already running | Hypothesis only | Correctly acknowledged as a manual, network-touching step (`README.md:184-197`); not offline-gated, which the PRD's US-005 AC#3 explicitly allows |
| Zero regressions: 82 stdio tests pass | Measurable — verified | Re-ran the 6 stdio test files: `82 passed` |

---

## Drift List

No design-intent drift detected. Two items worth flagging, both **non-blocking**:

- **`tests/test_docker_packaging.py:146-154` — environment-fragile skip guard (test robustness, not a code or design defect).** The gating test skips only when `shutil.which("docker") is None`. On a host with a Docker CLI but *without the compose-v2 plugin* (this machine: Docker present, `docker compose` → "unknown command"), the guard passes, the test runs `docker compose -f … config`, and it fails with `unknown shorthand flag: 'f'`. The compose file itself is well-formed (validated directly and via `load_registry` on the sample). This produces a false-negative test failure on such hosts. A hardened guard would additionally probe `docker compose version` success. The feature and the offline file/content assertions are unaffected. Task-8's note said the test "skips when docker absent," which is literally true but does not cover docker-present-compose-absent.

- **`src/okf_mcp_server/gateway/app.py:139-143` — TTL refresh runs on *every* `/{owner}/mcp` request and re-points `session_manager.app` for the whole manager.** This is the design's intended "new sessions bind whatever `app` is at connect time" model, and it is safe for the reviewed use, but it is a shared-mutable-state pattern: a refresh triggered by one caller mutates the single `session_manager.app` all callers share. Because MCP handlers are stateless reads over `build_server(docs)` output and the swap is a single reference assignment, no correctness bug manifests; worth a note only as a latent coupling if per-session isolation is ever needed.

---

## Reviewer Notes

- **Cross-task contract consistency is excellent.** The `servers.yaml` schema (defaults/owners/credentials with `extra='forbid'`), the two auth surfaces, and the `/{owner}/mcp` + `/{owner}/refresh` + `/healthz` routing contract line up across `registry.py`, `git_source.py`, `owner_cache.py`, `app.py`, `docker-compose.yml`, `.env.example`, `servers.yaml`, and `README.md`. The sample `servers.yaml` is internally consistent at runtime: `beta`'s host has a credentials entry whose `token_env` (`OKF_GIT_TOKEN_BITBUCKET`) is exactly the variable in `.env.example`, while `acme`'s public host has none (anonymous clone) — the provider-neutral resolution path is genuinely data-driven.

- **The additive-not-a-refactor invariant genuinely holds.** `git diff --stat` over the full range shows zero lines touched in the stdio source files, and the six stdio test files are unmodified. `tests/conftest.py` changed but only additively: the `sample_repo` fixture's semantics are preserved verbatim; `make_bare_repo`/`push_commit`/`FakeClock` are new.

- **Test coverage is sound and offline.** Security-relevant claims are backed by real assertions rather than mocks-only: the clean-remote invariant is checked against an actual `.git/config` (`test_git_source_auth.py:176-187`), token redaction is checked on a simulated `CalledProcessError` (`:149-173`), and the double-pull/lock claim uses a real spy with a widened overlap window (`test_owner_cache.py:186-224`). The 60s default TTL has a dedicated literal-pinned test (`test_registry.py:86-96`), satisfying US-003 AC#8.

- **Deferred items confirmed still open, as the task notes stated (all non-blocking):** no `--` separator before git positionals (`ref`/`url` come from a trusted operator `servers.yaml`, not consumer input, so flag-injection risk is minimal); no lowercase-normalization of credential host keys (a `servers.yaml` `credentials` key must match the URL host's case — an operator-facing gotcha worth a future one-liner); and the token is briefly present in the git argv (inherent to the AC-prescribed `https://user:token@host` URL form, mitigated by redaction on failure).

- **Recommendation (optional, non-blocking):** harden the `docker compose config` skip guard to also require a working compose-v2 plugin, so the gating test doesn't false-fail on docker-without-compose hosts. Consider a follow-up backlog task for the two deferred `git_source` hardening items if a private-host deployment is imminent.

---

## Pipeline-hygiene warning (non-blocking)

TASK-4..8 each reference `design/http-gateway-brainstorm.md` in their descriptions, tripping the ralph-task "Distilled for ralph-task" contract scan. These are ralph-backlog (PRD-derived) tasks that also carry the distilled shared contracts inline, so the brainstorm pointer is supplementary context, not the sole source — the same lower-risk pattern noted in the pre-implementation review.
