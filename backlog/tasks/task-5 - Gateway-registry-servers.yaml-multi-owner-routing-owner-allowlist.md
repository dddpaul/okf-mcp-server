---
id: TASK-5
title: 'Gateway registry (servers.yaml), multi-owner routing, owner allowlist'
status: Done
assignee: []
created_date: '2026-07-02 18:04'
updated_date: '2026-07-03 05:39'
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
- [x] #1 gateway/registry.py parses servers.yaml into validated pydantic models: defaults (ref, ttl), owners ({owner: {url, ref?, ttl?}}), and credentials ({host: {token_env, token_user}})
- [x] #2 Per-owner ref/ttl fall back to the defaults block when omitted
- [x] #3 Two distinct owners are served independently, each at its own /{owner}/mcp path
- [x] #4 A request for an unregistered owner returns HTTP 404
- [x] #5 Registered owners are eager-cloned in a background task at startup; an owner whose clone is still in flight resolves lazily on first request without blocking other owners or /healthz
- [x] #6 A malformed or missing servers.yaml fails fast at startup with a clear, actionable error message
- [x] #7 Unit tests cover registry parsing, defaults merging, and validation-error cases
- [x] #8 Existing 82 stdio tests still pass
- [x] #9 uv run mypy . and uv run ruff check . pass
- [x] #10 uv run pytest passes
- [x] #11 New deps (pydantic, pyyaml) are added via uv add and reflected in pyproject.toml and uv.lock
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: (1) gateway/registry.py — pydantic models Defaults(ref,ttl), OwnerSpec(url,ref?,ttl?), Credential(token_env,token_user), Registry(defaults,owners,credentials) with extra='forbid'; ResolvedOwner dataclass; Registry.resolve(owner) merges defaults; load_registry(path)->Registry raising RegistryError(ValueError) with actionable messages for missing/unreadable/non-YAML/non-mapping/empty/no-owners/schema-invalid. (2) gateway/app.py — refactor create_app(registry,cache_dir) to multi-owner lazy: OwnerState per owner (asyncio.Event ready, session_manager, checkout, error); lifespan spawns one background task per owner that clones+builds via asyncio.to_thread (non-blocking) then holds session_manager.run() until shutdown; _MCPRouter dispatches /{owner}/mcp by path_params -> 404 unknown owner, await ready (lazy resolve), 503 on error, else handle_request; /healthz open+immediate. app.state.owners exposed. (3) gateway/config.py — GatewayConfig{servers_path,cache_dir} from env (OKF_GATEWAY_SERVERS/OKF_GATEWAY_CACHE_DIR). (4) __main__.py — load_registry (fail fast, SystemExit on RegistryError) then create_app. (5) tests/test_registry.py (AC7 parse/defaults/validation) + rewrite tests/test_gateway.py (2 owners independent, 404, lazy-resolve non-blocking, content-from-clone). Deps pydantic+pyyaml added via uv add (+types-PyYAML dev).

Commit: `672693e` - task-5: add servers.yaml registry, multi-owner routing, and owner allowlist

Implemented US-002. registry.py: pydantic Defaults/OwnerSpec/Credential/Registry (extra='forbid'), Registry.resolve() merges per-owner ref/ttl over defaults (built-in main/60), load_registry() raises RegistryError with actionable messages (missing/unreadable/non-YAML/non-mapping/empty/no-owners/schema-invalid). app.py refactored from TASK-4 single-owner clone-then-serve to multi-owner serve-then-lazy-resolve: per-owner OwnerState + background _serve_owner task clones+builds off-loop via asyncio.to_thread then holds session_manager.run() until shutdown; _MCPRouter dispatches /{owner}/mcp by path_params (404 unregistered, await ready = lazy resolve, 503 on clone failure, else handle_request); /healthz open+immediate; failures isolated per owner. config.py -> GatewayConfig{servers_path,cache_dir} from OKF_GATEWAY_SERVERS/OKF_GATEWAY_CACHE_DIR; __main__ loads registry (fail-fast SystemExit(1)) before uvicorn. Tests: test_registry.py (15), test_gateway.py multi-owner (6: 2-owners-independent, 404, lazy-non-blocking, content-from-clone), test_gateway_main.py (2 wiring). Gates: 105 passed (stdio still exactly 82), mypy+ruff clean. Deps pydantic+pyyaml via uv add (+types-PyYAML dev). task-reviewer: APPROVED. Reviewer nit (registry.py over-long validation line) fixed.
<!-- SECTION:NOTES:END -->
