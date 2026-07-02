---
id: TASK-8
title: 'Gateway Docker packaging, compose, and README'
status: To Do
assignee: []
created_date: '2026-07-02 18:09'
updated_date: '2026-07-02 20:30'
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
- [ ] #1 A Dockerfile (python-slim base + git + uv) installs the package and runs okf-mcp-gateway
- [ ] #2 docker-compose.yml sets restart: unless-stopped, publishes 8080:8080, uses env_file .env (OKF_GATEWAY_TOKEN, OKF_GIT_TOKEN_*), mounts a named cache volume for checkouts, mounts servers.yaml read-only, and defines a healthcheck hitting /healthz
- [ ] #3 docker compose config validates the compose file (offline, gating); actual docker build / up -d is documented as a manual verification step
- [ ] #4 README gains a Gateway section: what it is, a servers.yaml example, the env vars, docker compose up -d (noting idempotency), and a consumer .mcp.json snippet pointing at http://host.docker.internal:8080/{owner}/mcp with the bearer token
- [ ] #5 .env.example and a sample servers.yaml are committed with no real secrets
- [ ] #6 Existing 82 stdio tests still pass
- [ ] #7 uv run mypy . and uv run ruff check . pass
- [ ] #8 uv run pytest passes
- [ ] #9 The task/README explicitly notes that docker compose up -d idempotency (no-op when already running) is a manual verification step, not gated by an offline AC
<!-- AC:END -->
