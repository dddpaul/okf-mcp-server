# Feature Review: http-gateway

**Verdict: Aligned**

**Date:** 2026-08-05
**In-scope tasks:** TASK-4, 5, 6, 7, 8, 11, 12, 17 (context: TASK-13, TASK-14)
**Diff range:** `0e83a2348ef91da432a6acbcb7ce9089423ed760..HEAD`
**Passes run:** 1 (PRD coverage), 2 (Non-goal protection), 3 (Brainstorm scope cuts), 4 (Success-metric realism), 5 (Out-of-scope creep)
**Passes skipped:** none — both intent docs present; PRD has Non-Goals + Success Metrics; brainstorm has Scope cuts.

No custom rules file (`.claude/ralph-review-rules.md`) present; standard rubric only.

## Distillation soft-warnings (pipeline hygiene, non-blocking)

- Warning: TASK-4 references a brainstorm file in its description — distillation may have been skipped
- Warning: TASK-5 references a brainstorm file in its description — distillation may have been skipped
- Warning: TASK-6 references a brainstorm file in its description — distillation may have been skipped
- Warning: TASK-7 references a brainstorm file in its description — distillation may have been skipped
- Warning: TASK-8 references a brainstorm file in its description — distillation may have been skipped

These five tasks were created via the older `ralph-prd` → `ralph-backlog` pipeline, which references the source design doc; the newer per-task distillation contract (TASK-11/12/17) inlines the locked decisions instead. Non-blocking — the reviewer judged intent from the PRD/brainstorm directly.

## Intent → Implementation Matrix

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| US-001 / FR-1 | `/{owner}/mcp` Streamable HTTP reusing `load_docs`/`build_server` verbatim | Delivered | `gateway/app.py:132-164` (`_MCPRouter`), `owner_cache.py:381-384` (`_scan_docs` → `load_docs`), `_clone_blocking:313` (`build_server`) |
| US-001 / FR-2 | Git-sourced, no mounts | Delivered | `git_source.py:123-166` shallow `git clone --depth 1` into cache dir; `docker-compose.yml:32` named volume, no source mount |
| US-001 | `okf-mcp-gateway` console script; stdio path unchanged | Partial | Script in `pyproject.toml`; **but** `server.py` was modified (see Drift) |
| US-001 | `GET /healthz` 200 immediately | Delivered | `app.py:406-407`, `:500`; lifespan clones in background tasks `:482-493` |
| US-002 / FR-3 | `servers.yaml` schema (defaults/owners/credentials), pydantic-validated | Delivered | `registry.py:46-120`, `extra="forbid"` on every model |
| US-002 / FR-4 | Unregistered owner → 404 | Delivered | `app.py:149-153` (mcp), `:445-448` (refresh) |
| US-002 / FR-10 | Eager background clone; lazy first-request resolve; malformed registry fails fast | Delivered | `app.py:482-493`, `_MCPRouter:154` awaits `ready`; `registry.py` `RegistryError`; `__main__.py:44-48` |
| US-003 / FR-7 | TTL pull-on-demand (default 60, per-owner override) | Delivered | `owner_cache.py:214-253`, `registry.py:35` `DEFAULT_TTL=60`, `OwnerSpec.ttl` override |
| US-003 / FR-8 | `POST /{owner}/refresh` forces pull, JSON summary | Delivered | `app.py:442-480`, `RefreshResult` `owner/ref/commit/docs_loaded` |
| US-003 / FR-9 | Per-owner async lock; owners independent | Delivered | `owner_cache.py:155` per-instance `asyncio.Lock`, re-check under lock `:239-242` |
| US-004 / FR-5 | North bearer on all routes but `/healthz`; 401 otherwise | Delivered | `app.py:167-206`, constant-time compare `:204`, `/healthz` exempt `:185` |
| US-004 / FR-6 | South per-host token-in-URL; clean stored remote; redacted errors | Delivered | `git_source.py:44-87` builder, `:163-165` `remote set-url` clean, `:90-120` `_run_git` redaction |
| US-005 / FR-11 | Dockerfile + compose (restart, healthcheck, cache volume, `servers.yaml:ro`, `8080:8080`) | Delivered | `docker-compose.yml:15-35`; README gateway section present |
| FR-12 | Stdio path + 82 tests untouched and green | Partial | Tests green, but `server.py` + `test_server.py` were modified (see Drift) |
| Addendum `/status` (2026-07-17) | Global bearer-gated read-only status; state enum; two clocks; scrub | Delivered | `app.py:262-346`, `owner_cache.py` `wall_clock`/`last_pulled_wall`, `_scrub_credentials:61-63` |
| Addendum `/config` (TASK-11) | Effective config, `?format=`, credential scrub (token_env only, never value) | Delivered | `app.py:209-259`, `:409-427`; credentials emit `token_env`/`token_user` only |
| **Addendum offline-fallback (2026-08-04 / TASK-17)** | Branch table; never rmtree good checkout; `rev-parse` integrity gate; CredentialError→stale; get_or_refresh serves stale + self-heals; force_refresh→502; 4 new `/status` fields; stale owner = `serving` | Delivered | `owner_cache.py:166-212` (branch table + `_valid_checkout_exists:341-361` + `_serve_existing:363-379`), `:214-253` non-raising, `:255-290`+`RefreshUnavailable`, `app.py:442-468` 502 mapping, `:310-330` four fields + `stale` derivation, `:299-303` stale kept `serving` |

## Non-Goal Violations

None detected. Live-working-tree serving is absent (git clone only, `git_source.py:1-4`); single multi-owner gateway (no per-owner containers); no third-party proxy (`grep` for `mcp-proxy`/`supergateway` → none in `src/`); no launchd/systemd (only a comment noting their deliberate absence); `/refresh` exists but no webhook is wired; no per-token scoping / IP allowlist (the single `BearerAuthMiddleware` remains the drop-in point); no internal-CA bundling in the shipped image path.

## Scope Cut Violations

None detected. TASK-17's cuts are honored: no background serve-then-refresh task (synchronous `load()` in `owner_cache.py:166`), no "offline mode" config flag (fallback is automatic on exception), no volume-layout change (existing `okf-checkouts` volume + per-owner dirs reused).

## Success Metric Assessment

| Metric | Status | Notes |
|--------|--------|-------|
| Devcontainer reads owner over HTTP with bearer, no mount | Measurable post-merge | Exercised by `tests/test_gateway.py` (TestClient list/read at `/{owner}/mcp` from `file://` fixture); live devcontainer is a documented manual step |
| Adding an owner = one-line `servers.yaml` edit | Measurable post-merge | Registry parsing/defaults-merge tests in `tests/test_registry.py` |
| Bitbucket→GitHub migration = data-only `url` change | Hypothesis only | Provider-neutral resolution proven in `tests/test_git_source_auth.py`; no migration test, acceptable |
| `docker compose up -d` idempotent | Hypothesis only | `restart: unless-stopped` present; actual idempotency is a documented manual check (compose `config` gating test is env-blocked here) |
| Zero regressions: 82 stdio tests pass | Measurable — with caveat | Stdio tests pass, but `test_server.py` gained 104 lines and `server.py` behavior changed; "untouched" is not literally true (see Drift) |

## Drift List

- **`src/okf_mcp_server/server.py:1-171` — shared stdio core modified, contradicting the repeatedly-locked "completely untouched" constraint.** The PRD (US-001 AC "existing `run()`/`serve_stdio`/`cli.py` unchanged"; FR-12; Success Metric "82 stdio tests still pass, untouched") and brainstorm ("`config.py`/`server.py`/`cli.py`/`run()`/`serve_stdio` untouched") lock `server.py` as immutable. It was changed by the two context tasks: TASK-13 added symlink-skipping in `_iter_markdown_files:86` and URI dedup in `load_docs:118-131`; TASK-14 added `ParsedDoc.content_hash:46-60` and changed `build_server`'s `read_resource` return type from bare `str` to `Iterable[ReadResourceContents]` (`server.py:151-168`). This is a behavior change to the shared core the gateway reuses. Because these are *context* tasks (13/14), not in the primary http-gateway scope, and they are additive/backward-compatible with all preserved existing tests, this is a documentation-vs-reality drift rather than a functional regression — but the "untouched" wording in the locked design is now false and should be reconciled (either amend the constraint or note the exception).
- **`tests/test_server.py:330-397` — the stdio test file was edited (+104 lines).** The locked constraint says the 82 stdio tests remain "untouched and green" and "their files are unchanged". The existing tests were preserved (additive only), so the intent (no regressions) holds, but the literal "files unchanged" claim is violated by TASK-14's new tests.

## Reviewer Notes

- The **primary in-scope feature (TASK-4/5/6/7/8/11/12/17) is faithfully and thoroughly implemented.** TASK-17 (the newest locked intent) is a precise realization of the offline-fallback addendum — the branch table, the `_valid_checkout_exists` `git rev-parse HEAD` integrity gate, "never rmtree a good checkout," CredentialError-as-source-unavailable (empty volume still fails via `clone_owner`'s rmtree path), non-raising `get_or_refresh` with self-heal (success clock only stamped on `source_available=True`, `owner_cache.py:413-415`, keeping the owner past-TTL), `RefreshUnavailable`→502, and all four new `/status` fields with the `stale` derivation and stale-owner-stays-`serving` rule are all present and correct.

- **Test-suite state:** `178 passed, 1 failed`. The single failure is `tests/test_docker_packaging.py::test_docker_compose_config_validates` — an **environment fault, not a code defect**: the sandbox Docker (v29.7.1) reports `docker: unknown command: docker compose`, so `docker compose -f …` returns exit 125 before touching the compose file. The compose file itself is well-formed (`restart: unless-stopped`, `8080:8080`, `env_file`, `okf-checkouts` volume, `./servers.yaml:/app/servers.yaml:ro`, `/healthz` healthcheck all present). `mypy` and `ruff` are clean across 29 source files.

- **Minor addition beyond spec (not drift):** `_MCPRouter` returns **503** for an owner that finished loading without a session manager (`app.py:155-159`); likewise `POST /refresh` `:450-453`. The design specs 401/404 for the north surface and 502 for source-down refresh but never mention 503 for a hard-failed owner. This is a reasonable, non-contradicting addition (a `failed` owner genuinely has nothing to serve) and is distinct from the 502 stale-but-serving path, so it does not conflict with any locked decision.
