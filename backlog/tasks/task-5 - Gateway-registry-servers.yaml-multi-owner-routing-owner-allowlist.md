---
id: TASK-5
title: 'Gateway registry (servers.yaml), multi-owner routing, owner allowlist'
status: To Do
assignee: []
created_date: '2026-07-02 18:04'
updated_date: '2026-07-02 20:30'
labels:
  - 'feature:http-gateway'
dependencies:
  - TASK-4
priority: high
ordinal: 5000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
US-002. Introduce the servers.yaml registry and serve multiple owners, each at /{owner}/mcp. The registry is the authoritative owner allowlist. Depends on the vertical slice (TASK-4). Shared servers.yaml schema (all gateway tasks honor it): top-level 'defaults' (ref, ttl); 'owners' as {owner: {url, ref?, ttl?}}; 'credentials' as {host: {token_env, token_user}} (parsed+validated here; consumed in the auth task). Story: design/http-gateway-prd.md US-002; context: design/http-gateway-brainstorm.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 gateway/registry.py parses servers.yaml into validated pydantic models: defaults (ref, ttl), owners ({owner: {url, ref?, ttl?}}), and credentials ({host: {token_env, token_user}})
- [ ] #2 Per-owner ref/ttl fall back to the defaults block when omitted
- [ ] #3 Two distinct owners are served independently, each at its own /{owner}/mcp path
- [ ] #4 A request for an unregistered owner returns HTTP 404
- [ ] #5 Registered owners are eager-cloned in a background task at startup; an owner whose clone is still in flight resolves lazily on first request without blocking other owners or /healthz
- [ ] #6 A malformed or missing servers.yaml fails fast at startup with a clear, actionable error message
- [ ] #7 Unit tests cover registry parsing, defaults merging, and validation-error cases
- [ ] #8 Existing 82 stdio tests still pass
- [ ] #9 uv run mypy . and uv run ruff check . pass
- [ ] #10 uv run pytest passes
- [ ] #11 New deps (pydantic, pyyaml) are added via uv add and reflected in pyproject.toml and uv.lock
<!-- AC:END -->
