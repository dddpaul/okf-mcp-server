---
id: TASK-11
title: Gateway GET /config endpoint (effective config as JSON or YAML)
status: Done
assignee: []
created_date: '2026-07-17 07:24'
updated_date: '2026-07-17 07:44'
labels:
  - 'feature:http-gateway'
dependencies: []
priority: medium
ordinal: 11000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add a global GET /config endpoint to the multi-owner gateway that prints the effective runtime configuration. It lives alongside /healthz and /{owner}/refresh in create_app. Because BearerAuthMiddleware gates every route except /healthz, /config is automatically behind the north bearer token (OKF_GATEWAY_TOKEN) — an anonymous caller cannot read it.

Format: default JSON; ?format=yaml switches to YAML (pyyaml is already a dep, imported in registry.py). An unsupported format value is a 400.

Output is EFFECTIVE config only (no live pull state):
- process: servers_path, cache_dir, host, port, auth_required
- defaults: ref, ttl
- owners: {name: {url, ref, ttl}} with ref/ttl RESOLVED against the defaults block (via registry.resolve)
- credentials: {host: {token_env, token_user}} — env-var NAMES and username only; the endpoint MUST NEVER resolve or print the secret token value

Wiring: create_app gains optional servers_path/host/port params (default None); __main__.main() passes GatewayConfig.servers_path plus the resolved host/port. Reuse the existing app.state introspection pattern.

Shared contracts to honor: servers.yaml schema (defaults/owners/credentials), the two auth surfaces, and /{owner}/mcp routing are unchanged. Hard constraint: the existing stdio path (run()/serve_stdio/cli.py) and its 82 tests stay untouched and green. All ACs offline-verifiable via Starlette TestClient — no live network/Bitbucket/secrets.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 GET /config returns 200 with a JSON body by default whose top-level keys are process, defaults, owners, credentials
- [x] #2 The process block contains servers_path, cache_dir, host, port, and auth_required
- [x] #3 Each owners entry shows RESOLVED url/ref/ttl — an owner that omits ref/ttl reflects the defaults block values
- [x] #4 credentials entries expose only token_env and token_user; no secret token value appears anywhere in the response (asserted with a token set in the environment)
- [x] #5 GET /config?format=yaml returns 200 with a YAML body that yaml.safe_load round-trips to the same structure as the JSON body
- [x] #6 An unsupported ?format= value (e.g. xml) returns 400
- [x] #7 When auth is configured, /config requires the bearer token: missing/wrong token returns 401, correct token returns 200; GET /healthz stays open
- [x] #8 README gateway section documents GET /config and the ?format= parameter
- [x] #9 The existing 82 stdio tests remain green and their test files are unchanged
- [x] #10 Lint passes (uv run mypy . && uv run ruff check .)
- [x] #11 Tests pass (uv run pytest)
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: (1) app.py — add module-level _effective_config(registry, servers_path, cache_dir, host, port, auth_required) building {process, defaults, owners(resolved via registry.resolve), credentials(token_env+token_user only, never secret)} as a JSON/YAML-ready mapping. (2) create_app gains keyword-only servers_path/host/port params (default None); add GET /config route whose handler picks JSON (default) or YAML (?format=yaml) via yaml.safe_dump, 400 on unsupported format; surface servers_path/host/port on app.state for introspection parity. (3) __main__.main() resolves host/port before create_app and passes servers_path+host+port. (4) tests/test_gateway_config.py via Starlette TestClient (no lifespan → no clones/network): AC1-7. (5) extend test_gateway_main.py to assert wiring. (6) README gateway section documents GET /config + ?format=. Constraint: 82 stdio tests untouched & green.

Commit: `59f9bc4` - task-11: add gateway GET /config endpoint (effective config as JSON/YAML)

Commit: `2bbcf63` - task-11: assert north token is never echoed in /config response

Implemented GET /config via module-level _effective_config() + a create_app route: default JSON, ?format=yaml -> YAML (yaml.safe_dump), unsupported format -> 400. Owners' ref/ttl resolved via registry.resolve; credentials expose token_env/token_user names only (secret token never read from env nor emitted). create_app gained keyword-only servers_path/host/port (default None) surfaced on app.state; __main__.main() now resolves host/port first and forwards them. Sits behind BearerAuthMiddleware (all routes but /healthz). Tests: tests/test_gateway_config.py (7 tests, Starlette TestClient, offline/no-lifespan so no clones) cover AC1-7 incl. secret-absence and YAML round-trip; +1 wiring test in test_gateway_main.py. README 'Inspect the effective config' section added. 82 stdio tests untouched and green; mypy+ruff clean; pytest 154 passed/1 skipped. task-reviewer verdict: APPROVED.
<!-- SECTION:NOTES:END -->
