---
id: TASK-7
title: Gateway north bearer auth and south per-host git credentials
status: Done
assignee: []
created_date: '2026-07-02 18:09'
updated_date: '2026-07-03 06:28'
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
- [x] #1 One ASGI auth middleware requires Authorization: Bearer <OKF_GATEWAY_TOKEN> on /{owner}/mcp and /{owner}/refresh, returning HTTP 401 when the header is missing or wrong
- [x] #2 GET /healthz remains open (no token required)
- [x] #3 gateway/git_source.py resolves credentials per git host: parse host from the owner url, look up credentials[host], read the token from its token_env, and build the authenticated clone/fetch URL https://<token_user>:<token>@host/...
- [x] #4 When no credential entry matches the host, the clone runs unauthenticated (public repos work)
- [x] #5 The stored git remote in the cache checkout contains NO credentials (token injected per-invocation only), verified by inspecting the fixture checkout's .git/config
- [x] #6 Unit test: given token_user + a token env var the URL builder produces the exact expected authenticated URL, and given no credential entry it produces the clean URL (no live authenticated host needed)
- [x] #7 Existing 82 stdio tests still pass
- [x] #8 uv run mypy . and uv run ruff check . pass
- [x] #9 uv run pytest passes
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan (US-004):
North auth — add BearerAuthMiddleware (ASGI) in gateway/app.py: exempt GET /healthz, require Authorization: Bearer <token> on all other routes (constant-time compare, WWW-Authenticate: Bearer on 401). create_app gains auth_token kwarg (None=no middleware, backward-compat); sets app.state.auth_required. __main__ reads OKF_GATEWAY_TOKEN, fails fast if unset, passes to create_app.
South creds — gateway/git_source.py: add build_authenticated_url(url, credentials, env) parsing host, looking up credentials[host], reading token_env, building https://<token_user>:<token>@host/... (percent-encoded); no entry -> clean url; entry but env unset -> CredentialError. clone_owner/fetch_and_reset gain credentials+env kwargs, inject per-invocation, store CLEAN remote (git remote set-url origin <clean> after clone; fetch from explicit auth url). Sanitize CalledProcessError to redact token. owner_cache/OwnerCache threads credentials; create_app passes registry.credentials.
Tests — build_authenticated_url cases (AC6), clone/fetch command-construction + clean-remote (AC3/AC5), 401 missing/wrong + healthz-open + valid-token MCP (AC1/AC2), main token wiring. Update 3 monkeypatch spies (clone/fetch signatures) + gateway_main tests for token.

Commit: `a7abacd` - task-7: north bearer auth middleware and south per-host git credential injection

Implemented US-004 (reviewer: APPROVED; mypy+ruff clean; pytest 132 passed).
North: gateway/app.py BearerAuthMiddleware — single ASGI choke point outside the router; exempts GET /healthz, requires Authorization: Bearer <OKF_GATEWAY_TOKEN> on all other routes, 401 (WWW-Authenticate: Bearer) on missing/wrong via constant-time secrets.compare_digest on bytes. Unauthenticated callers get 401 before routing so owners can't be enumerated (401 precedes 404). create_app gained auth_token kwarg (None=open for tests) and app.state.auth_required; __main__ reads OKF_GATEWAY_TOKEN and fails fast if unset.
South: gateway/git_source.py build_authenticated_url(url, credentials, env) parses host, looks up credentials[host], reads token_env, builds https://<token_user>:<token>@host/... (percent-encoded). No entry -> clean url (public repos). Entry but env unset -> CredentialError (fail fast). clone_owner/fetch_and_reset inject per-invocation and keep the stored remote CLEAN (git remote set-url origin <clean> after clone; fetch from explicit auth url); _run_git redacts the token from any CalledProcessError. owner_cache threads registry.credentials through.
Tests: new tests/test_git_source_auth.py (URL builder, clone/fetch argv + clean remote + real .git/config, redaction); north auth tests + main token wiring; updated 3 monkeypatch spies to new signatures.
Deferred (reviewer non-blocking, out of scope): lowercase-normalize credential host keys at registry load; note token is briefly in git argv (ps) — inherent to the AC-prescribed URL form. README/Docker are TASK-8 scope.
<!-- SECTION:NOTES:END -->
