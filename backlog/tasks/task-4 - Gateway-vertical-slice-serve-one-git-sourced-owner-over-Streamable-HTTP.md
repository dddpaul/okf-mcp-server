---
id: TASK-4
title: 'Gateway vertical slice: serve one git-sourced owner over Streamable HTTP'
status: Done
assignee: []
created_date: '2026-07-02 18:02'
updated_date: '2026-07-03 05:18'
labels:
  - 'feature:http-gateway'
dependencies: []
priority: high
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
US-001. Additive okf-mcp-gateway entry point. Serve ONE owner's docs over MCP Streamable HTTP at /{owner}/mcp, sourcing content from a git clone (no mount). Reuse the existing core verbatim; do not touch the stdio path. Thin end-to-end slice — auth, multi-owner registry, TTL/refresh, and Docker come in later tasks. Shared routing contract: every owner served at /{owner}/mcp. Full design: design/http-gateway-brainstorm.md; story: design/http-gateway-prd.md US-001.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 New okf_mcp_server/gateway/ package exists and an okf-mcp-gateway console script is registered in pyproject.toml
- [x] #2 Existing stdio surface (run(), serve_stdio, cli.py, server.py, config.py) is unchanged — no edits to those files
- [x] #3 Given one owner (name + git URL + ref via minimal config/env), the gateway shallow-clones the repo into a cache directory and loads docs by calling the existing load_docs and build_server verbatim (no fork/copy of that logic)
- [x] #4 GET /healthz returns HTTP 200 once the app is up
- [x] #5 A Starlette TestClient MCP Streamable HTTP session can list_resources and read_resource for the owner at /{owner}/mcp, returning the same docs the stdio server would
- [x] #6 Served content demonstrably originates from a git clone of a file:// bare-repo fixture, not from a mounted or working-tree path
- [x] #7 Existing 82 stdio tests still pass
- [x] #8 uv run mypy . and uv run ruff check . pass
- [x] #9 uv run pytest passes
- [x] #10 tests/conftest.py provides a reusable fixture that builds a file:// bare-repo git source (extending the existing git-init pattern), reused by this and later gateway tasks
- [x] #11 load_docs and build_server are reused with unchanged signatures by constructing a per-owner ServerConfig(owner=<name>, roots=(<checkout_path>,)) — no edits to those functions
- [x] #12 New runtime deps (starlette, uvicorn) are added via uv add and reflected in pyproject.toml and uv.lock
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan (US-001 vertical slice):
- Add starlette+uvicorn via uv add; register okf-mcp-gateway console script.
- New okf_mcp_server/gateway/ pkg: config.py (GatewayConfig+from_env), git_source.py (shallow clone_owner), app.py (create_app -> Starlette: /healthz + /{owner}/mcp via StreamableHTTPSessionManager, lifespan runs session_manager.run()), __main__.py (uvicorn.run).
- Reuse load_docs/build_server verbatim by building ServerConfig(owner, roots=(checkout,)).
- conftest: reusable bare_repo_factory building file:// bare repos (extends git-init pattern).
- tests/test_gateway.py: healthz 200; MCP client (httpx ASGITransport) list_resources+read_resource at /{owner}/mcp; assert checkout under cache dir with .git remote = file:// bare (git-clone provenance, not mount).
- Do NOT touch stdio files (config.py/server.py/cli.py/__init__.py).

Commit: `1ae5ef3` - task-4: add okf-mcp-gateway single-owner Streamable HTTP slice

Done — US-001 vertical slice implemented and task-reviewer APPROVED (all 12 AC met).

Implementation:
- New src/okf_mcp_server/gateway/ package: config.py (GatewayConfig.from_env: OKF_GATEWAY_OWNER/GIT_URL/GIT_REF/CACHE_DIR), git_source.py (clone_owner: git clone --depth 1 --branch <ref> into cache), app.py (create_app -> Starlette: GET /healthz + ASGI /{owner}/mcp via StreamableHTTPSessionManager in app lifespan; _MCPHandler is a callable class so all HTTP methods reach the transport), __main__.py (okf-mcp-gateway console script, uvicorn, default 0.0.0.0:8080).
- Core reused verbatim via ServerConfig(owner, roots=(checkout,)) -> load_docs -> build_server; stdio surface untouched.
- conftest: reusable make_bare_repo fixture (file:// bare repos) + GitRepoFixture; tests/test_gateway.py drives MCP list/read over httpx.ASGITransport and asserts git-clone provenance.
- Deps: uv add starlette uvicorn (pyproject + uv.lock).

Verification: mypy + ruff clean; 86 pytest (82 stdio + 4 gateway) green. Also smoke-tested the real okf-mcp-gateway console script over live HTTP (uvicorn on 127.0.0.1:8137): /healthz 200 and an MCP Streamable HTTP client listed+read the doc from the git clone.

Test-client note: AC #5 driven via httpx.ASGITransport (the same transport Starlette TestClient wraps) because the MCP Streamable HTTP session is async; Starlette's sync TestClient cannot drive it directly.

Deferred (reviewer non-blocking, for multi-owner/registry task): add '--' separator before git clone positionals to harden against leading-dash URLs; surface captured git stderr on clone failure.
<!-- SECTION:NOTES:END -->
