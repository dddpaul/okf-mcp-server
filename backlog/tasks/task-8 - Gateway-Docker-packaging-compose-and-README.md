---
id: TASK-8
title: 'Gateway Docker packaging, compose, and README'
status: Done
assignee: []
created_date: '2026-07-02 18:09'
updated_date: '2026-07-03 10:09'
labels:
  - 'feature:http-gateway'
dependencies:
  - TASK-6
  - TASK-7
priority: medium
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
US-005. Package the gateway as a supervised container and document how a devcontainer points at it. Depends on the TTL/refresh task (TASK-6) and the auth task (TASK-7, for env/config). Docker restart policy is the cross-platform keep-alive (no launchd/systemd); docker compose up -d is the idempotent start. Gating ACs are offline: docker compose config validation + file/content checks; actual docker build/up is a documented manual step (pulls base images over the network). Story: design/http-gateway-prd.md US-005; context: design/http-gateway-brainstorm.md.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 A Dockerfile (python-slim base + git + uv) installs the package and runs okf-mcp-gateway
- [x] #2 docker-compose.yml sets restart: unless-stopped, publishes 8080:8080, uses env_file .env (OKF_GATEWAY_TOKEN, OKF_GIT_TOKEN_*), mounts a named cache volume for checkouts, mounts servers.yaml read-only, and defines a healthcheck hitting /healthz
- [x] #3 docker compose config validates the compose file (offline, gating); actual docker build / up -d is documented as a manual verification step
- [x] #4 README gains a Gateway section: what it is, a servers.yaml example, the env vars, docker compose up -d (noting idempotency), and a consumer .mcp.json snippet pointing at http://host.docker.internal:8080/{owner}/mcp with the bearer token
- [x] #5 .env.example and a sample servers.yaml are committed with no real secrets
- [x] #6 Existing 82 stdio tests still pass
- [x] #7 uv run mypy . and uv run ruff check . pass
- [x] #8 uv run pytest passes
- [x] #9 The task/README explicitly notes that docker compose up -d idempotency (no-op when already running) is a manual verification step, not gated by an offline AC
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan (TASK-8, Docker packaging):
- Dockerfile: python:3.12-slim base + git + uv; copy project, uv sync --no-dev --frozen; install package; CMD okf-mcp-gateway. Non-root user; expose 8080.
- docker-compose.yml: service 'gateway'; restart: unless-stopped; ports 8080:8080; env_file .env; named volume 'okf-checkouts' mounted at OKF_GATEWAY_CACHE_DIR=/var/cache/okf-mcp-gateway; ./servers.yaml:/app/servers.yaml:ro; healthcheck curl -f http://localhost:8080/healthz.
- .env.example: OKF_GATEWAY_TOKEN + OKF_GIT_TOKEN_* placeholders (no real secrets); add .env to .gitignore.
- servers.yaml: sample owners+defaults+credentials (no secrets; credentials only name token_env).
- tests/test_docker_packaging.py: offline gating content checks on Dockerfile/compose (restart, port, env_file, volume, ro servers mount, healthcheck /healthz), sample servers.yaml validates via load_registry, .env.example has no secret values; run 'docker compose config' only if binary present (skip otherwise — docker absent in sandbox/CI).
- README: new Gateway section (what it is, servers.yaml example, env vars, docker compose up -d idempotency note = manual verify, consumer .mcp.json at http://host.docker.internal:8080/{owner}/mcp with bearer).
- Docker/network build+up documented as manual step; not gated (offline gate = compose config + content checks per AC#3/#9).
Docker binary is NOT available in this sandbox — offline gate relies on pytest content checks; docker compose config auto-skips when absent.

Commit: `289daa4` - task-8: Docker packaging, compose, .env/servers.yaml samples, and gateway README

Done (task-reviewer APPROVED). Implemented US-005 Docker packaging:
- Dockerfile: python:3.14-slim + git + uv; two-stage 'uv sync --frozen --no-dev'; non-root uid 10001 owns /app and the checkout cache; CMD okf-mcp-gateway.
- docker-compose.yml: restart: unless-stopped; 8080:8080; env_file .env (long-form required:false so 'docker compose config' validates before .env exists); named volume okf-checkouts at OKF_GATEWAY_CACHE_DIR; ./servers.yaml:/app/servers.yaml:ro; python-urllib healthcheck on /healthz (auth-exempt).
- .env.example (empty OKF_GATEWAY_TOKEN + OKF_GIT_TOKEN_BITBUCKET; no secrets); .env gitignored.
- servers.yaml sample (example.invalid hosts; credentials name env vars only; no secrets).
- tests/test_docker_packaging.py: 11 offline content/gating checks (always run) + 'docker compose config' that skips when docker is absent. .dockerignore added.
- README: new Gateway section (registry, env-var table, docker compose up -d idempotency = manual verify step, consumer .mcp.json at host.docker.internal:8080/{owner}/mcp with bearer).
Gates: ruff clean, mypy clean (26 files), pytest 143 passed + 1 skipped (docker compose config skips — no Docker in sandbox/CI). Actual docker build/up-d and up-d idempotency no-op documented as MANUAL steps (network), not offline-gated (AC#3/#9).
<!-- SECTION:NOTES:END -->
