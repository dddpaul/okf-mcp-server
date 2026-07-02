---
id: TASK-6
title: 'Gateway pull-on-demand TTL cache and POST /{owner}/refresh'
status: To Do
assignee: []
created_date: '2026-07-02 18:08'
updated_date: '2026-07-02 20:30'
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
- [ ] #1 gateway/owner_cache.py holds per-owner state (checkout path, loaded docs, built Server, last_pulled, asyncio.Lock) and a get_or_refresh(ttl) that, when staler than ttl, runs git fetch --depth 1 + reset --hard <ref> and on a changed tree re-runs load_docs and rebuilds the owner's Server
- [ ] #2 With a file:// fixture: after committing a change to the source, a request WITHIN ttl does not re-pull (served content unchanged) and a request AFTER ttl reflects the change; the TTL clock is injectable for deterministic tests
- [ ] #3 POST /{owner}/refresh forces an immediate pull regardless of ttl and returns a JSON summary containing owner, ref, commit, and docs_loaded
- [ ] #4 The per-owner asyncio.Lock prevents concurrent double-pulls (verified with a spy or concurrent-request test); a pull on one owner never blocks requests to another owner
- [ ] #5 Existing 82 stdio tests still pass
- [ ] #6 uv run mypy . and uv run ruff check . pass
- [ ] #7 uv run pytest passes
- [ ] #8 When both the owner ttl and defaults.ttl are omitted, the effective TTL default is 60 seconds, covered by a unit test
<!-- AC:END -->
