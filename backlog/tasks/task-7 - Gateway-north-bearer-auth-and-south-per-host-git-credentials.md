---
id: TASK-7
title: Gateway north bearer auth and south per-host git credentials
status: To Do
assignee: []
created_date: '2026-07-02 18:09'
labels:
  - 'feature:http-gateway'
dependencies:
  - TASK-5
priority: medium
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
US-004. Two separate auth surfaces. North (consumer->gateway): a shared bearer token gates HTTP access. South (gateway->git host): per-host read-only tokens authenticate clones/fetches, provider-neutral so a Bitbucket->GitHub migration is a data-only change. Depends on the registry (TASK-5, credentials schema). North: Authorization: Bearer <OKF_GATEWAY_TOKEN> on /{owner}/mcp and /{owner}/refresh -> 401 otherwise; /healthz open; registry = owner allowlist. South: resolve token via credentials[host].token_env and inject as https://<token_user>:<token>@host/... per invocation; never persist creds in the stored remote. Story: design/http-gateway-prd.md US-004; context: design/http-gateway-brainstorm.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 One ASGI auth middleware requires Authorization: Bearer <OKF_GATEWAY_TOKEN> on /{owner}/mcp and /{owner}/refresh, returning HTTP 401 when the header is missing or wrong
- [ ] #2 GET /healthz remains open (no token required)
- [ ] #3 gateway/git_source.py resolves credentials per git host: parse host from the owner url, look up credentials[host], read the token from its token_env, and build the authenticated clone/fetch URL https://<token_user>:<token>@host/...
- [ ] #4 When no credential entry matches the host, the clone runs unauthenticated (public repos work)
- [ ] #5 The stored git remote in the cache checkout contains NO credentials (token injected per-invocation only), verified by inspecting the fixture checkout's .git/config
- [ ] #6 Unit test: given token_user + a token env var the URL builder produces the exact expected authenticated URL, and given no credential entry it produces the clean URL (no live authenticated host needed)
- [ ] #7 Existing 82 stdio tests still pass
- [ ] #8 uv run mypy . and uv run ruff check . pass
- [ ] #9 uv run pytest passes
<!-- AC:END -->
