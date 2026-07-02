---
id: doc-1
title: HTTP Gateway Overview
type: guide
created_date: '2026-07-02 17:55'
---

# HTTP Gateway Overview

Reference sheet for the `feature:http-gateway` work. Full design in
`design/http-gateway-brainstorm.md`; user stories in `design/http-gateway-prd.md`.

## Goal

Add an additive `okf-mcp-gateway` entry point: a single, cross-platform,
multi-owner server that exposes knowledge over MCP **Streamable HTTP** at
`/{owner}/mcp`, sourcing each owner's content from git (shallow clone into a
gateway-owned cache — no mounts). Enables a devcontainer to read knowledge over
the network without mounting the source folder.

## Tech Stack

- Python 3.10+, `uv` for deps.
- MCP SDK (Streamable HTTP transport), Starlette + uvicorn (ASGI), pydantic
  (config models), PyYAML (registry). New deps added via `uv add`.
- Docker + docker-compose for lifecycle (`restart: unless-stopped`).
- Quality gate: `uv run mypy . && uv run ruff check .` and `uv run pytest`.

## Architecture

New `okf_mcp_server/gateway/` package wrapping the existing, untouched core:

- `registry.py` — parse/validate `servers.yaml` (pydantic).
- `git_source.py` — shallow clone/fetch/reset; per-host auth URL; clean stored remote.
- `owner_cache.py` — per-owner checkout + loaded docs + built `Server` +
  `last_pulled` + `asyncio.Lock`; TTL-gated `get_or_refresh`.
- `app.py` — Starlette app; bearer-auth middleware; routes `/{owner}/mcp`,
  `POST /{owner}/refresh`, `GET /healthz`.
- `__main__.py` — load config, background eager-clone, `uvicorn.run`.

Reused **verbatim** (do not fork): `load_docs`, `build_server`, `slugify_type`,
`extract_id` from `server.py`.

## Shared cross-task contracts (all tasks must honor)

- **`servers.yaml` schema:** top-level `defaults` (`ref`, `ttl`), `owners`
  (`{owner: {url, ref?, ttl?}}`), and `credentials` (`{host: {token_env, token_user}}`).
- **North auth:** `Authorization: Bearer <OKF_GATEWAY_TOKEN>` on `/{owner}/mcp`
  and `/{owner}/refresh` → 401 otherwise; `/healthz` open. Registry = owner
  allowlist (unregistered owner → 404).
- **South auth:** per-host token resolved via `credentials[host].token_env`,
  injected as `https://<token_user>:<token>@host/...`; no creds in stored remote.
- **Routing:** every owner served at `/{owner}/mcp` (MCP Streamable HTTP).

## Scope

**In:** gateway package, git-sourced content, TTL pull-on-demand + `/refresh`,
north+south auth, Docker packaging, README.

**Out (deferred):** git webhook wiring, per-token owner scoping, source-IP
allowlist, internal-CA bundling, live-working-tree serving, per-owner containers,
launchd/systemd, live-Bitbucket integration tests.

## Hard constraints

- Existing stdio path (`run()`, `serve_stdio`, `cli.py`) and its 82 tests stay
  **untouched and green**.
- All ACs offline-verifiable: `file://` bare-repo git fixtures + Starlette
  `TestClient`. No live Bitbucket, network, or secrets in gating ACs.

## Task Dependency Graph

    TASK-4 (US-001 vertical slice: one git-sourced owner over Streamable HTTP)
       └─ TASK-5 (US-002 servers.yaml registry, multi-owner routing, allowlist)
             ├─ TASK-6 (US-003 TTL cache + POST /{owner}/refresh)
             └─ TASK-7 (US-004 north bearer auth + south per-host git credentials)
                   └─ TASK-8 (US-005 Dockerfile + compose + README)

TASK-6 and TASK-7 both depend on TASK-5 and are independent siblings; TASK-8
depends on TASK-7 (needs auth env/config) and TASK-6.
