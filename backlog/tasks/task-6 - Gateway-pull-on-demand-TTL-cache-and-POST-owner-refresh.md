---
id: TASK-6
title: 'Gateway pull-on-demand TTL cache and POST /{owner}/refresh'
status: Done
assignee: []
created_date: '2026-07-02 18:08'
updated_date: '2026-07-03 06:04'
labels:
  - 'feature:http-gateway'
dependencies:
  - TASK-5
priority: medium
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
US-003. Serve committed content freshly-enough without pulling on every request, plus a manual force-pull endpoint. Depends on the registry (TASK-5). POST /{owner}/refresh is the same endpoint a git webhook will target later (webhook wiring is out of scope now). Story: design/http-gateway-prd.md US-003; context: design/http-gateway-brainstorm.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 gateway/owner_cache.py holds per-owner state (checkout path, loaded docs, built Server, last_pulled, asyncio.Lock) and a get_or_refresh(ttl) that, when staler than ttl, runs git fetch --depth 1 + reset --hard <ref> and on a changed tree re-runs load_docs and rebuilds the owner's Server
- [x] #2 With a file:// fixture: after committing a change to the source, a request WITHIN ttl does not re-pull (served content unchanged) and a request AFTER ttl reflects the change; the TTL clock is injectable for deterministic tests
- [x] #3 POST /{owner}/refresh forces an immediate pull regardless of ttl and returns a JSON summary containing owner, ref, commit, and docs_loaded
- [x] #4 The per-owner asyncio.Lock prevents concurrent double-pulls (verified with a spy or concurrent-request test); a pull on one owner never blocks requests to another owner
- [x] #5 Existing 82 stdio tests still pass
- [x] #6 uv run mypy . and uv run ruff check . pass
- [x] #7 uv run pytest passes
- [x] #8 When both the owner ttl and defaults.ttl are omitted, the effective TTL default is 60 seconds, covered by a unit test
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: (1) git_source.py: add fetch_and_reset(checkout, ref) [git fetch --depth 1 origin ref + reset --hard FETCH_HEAD] and head_commit(checkout) [rev-parse HEAD]. (2) New owner_cache.py: OwnerCache holds resolved, dest, checkout, docs, server, last_pulled, commit, asyncio.Lock, injectable clock (default time.monotonic). load() does initial clone+build; get_or_refresh(ttl) fast-path fresh check + double-checked-lock stale pull via asyncio.to_thread, rebuilds Server only on changed HEAD; force_refresh() unconditional pull -> RefreshResult(owner, ref, commit, docs_loaded). Blocking git+load_docs+build_server run off-loop in a worker thread; result applied on the loop for atomic swap. (3) app.py: OwnerState wraps an OwnerCache (checkout/ready preserved as delegating attrs); _serve_owner uses cache.load(); _MCPRouter calls get_or_refresh then repoints session_manager.app to freshest Server before dispatch; add POST /{owner}/refresh route -> force_refresh JSON. create_app gains injectable clock. (4) __init__.py exports OwnerCache/RefreshResult. Tests: TTL within/after (injected clock), /refresh JSON keys, concurrent no-double-pull spy, cross-owner non-blocking, literal 60s default. Verified fetch+reset reflects pushed change with depth=1 on a file:// bare repo.

Commit: `207910d` - task-6: add per-owner TTL pull-on-demand cache and POST /{owner}/refresh

Done. task-reviewer verdict: APPROVED. Gate: uv run mypy . clean (24 files), uv run ruff check . clean, uv run pytest = 115 passed (was 105; +10). Key decisions: (1) fetch_and_reset resets --hard to FETCH_HEAD, not a literal <ref> — a bare-refspec shallow 'git fetch --depth 1 origin <ref>' only moves FETCH_HEAD (not the local branch or refs/remotes), so FETCH_HEAD is what actually advances the tree and converges for fast-forward + force-push alike. (2) get_or_refresh uses a double-checked asyncio.Lock: unlocked fast-path freshness check, then re-check under the lock so concurrent stale requests collapse to a single pull; blocking git+load_docs+build_server run off-loop via asyncio.to_thread and the result is swapped in on the loop in one _apply step (no torn reads). load_docs/build_server rerun only when HEAD moved. (3) Owner independence: one OwnerCache (lock + worker thread) per owner, so a pull on one never blocks another. (4) Rebuilt Server is served by re-pointing session_manager.app before dispatch — verified against the MCP lib that a new session binds self.app at connect time while in-flight sessions keep their captured transport. (5) TTL clock injectable via create_app(clock=...); default TTL 60s from the registry. Review follow-up: dropped unused _PullOutcome.changed field. README 'Gateway' section intentionally left to US-005/TASK-8 per PRD.
<!-- SECTION:NOTES:END -->
