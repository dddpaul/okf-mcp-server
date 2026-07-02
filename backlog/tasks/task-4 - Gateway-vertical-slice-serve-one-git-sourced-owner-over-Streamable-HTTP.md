---
id: TASK-4
title: 'Gateway vertical slice: serve one git-sourced owner over Streamable HTTP'
status: To Do
assignee: []
created_date: '2026-07-02 18:02'
updated_date: '2026-07-02 20:30'
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
- [ ] #1 New okf_mcp_server/gateway/ package exists and an okf-mcp-gateway console script is registered in pyproject.toml
- [ ] #2 Existing stdio surface (run(), serve_stdio, cli.py, server.py, config.py) is unchanged — no edits to those files
- [ ] #3 Given one owner (name + git URL + ref via minimal config/env), the gateway shallow-clones the repo into a cache directory and loads docs by calling the existing load_docs and build_server verbatim (no fork/copy of that logic)
- [ ] #4 GET /healthz returns HTTP 200 once the app is up
- [ ] #5 A Starlette TestClient MCP Streamable HTTP session can list_resources and read_resource for the owner at /{owner}/mcp, returning the same docs the stdio server would
- [ ] #6 Served content demonstrably originates from a git clone of a file:// bare-repo fixture, not from a mounted or working-tree path
- [ ] #7 Existing 82 stdio tests still pass
- [ ] #8 uv run mypy . and uv run ruff check . pass
- [ ] #9 uv run pytest passes
- [ ] #10 tests/conftest.py provides a reusable fixture that builds a file:// bare-repo git source (extending the existing git-init pattern), reused by this and later gateway tasks
- [ ] #11 load_docs and build_server are reused with unchanged signatures by constructing a per-owner ServerConfig(owner=<name>, roots=(<checkout_path>,)) — no edits to those functions
- [ ] #12 New runtime deps (starlette, uvicorn) are added via uv add and reflected in pyproject.toml and uv.lock
<!-- AC:END -->
