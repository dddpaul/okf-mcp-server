---
id: TASK-16
title: >-
  Update okf-mcp-server ralph-infra (.mcp.json + devcontainer) to the current
  ralph MCP gateway slot
status: In Progress
assignee: []
created_date: '2026-08-02 09:56'
updated_date: '2026-08-02 10:03'
labels: []
dependencies: []
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Run ralph-init upgrade to adopt the current ralph plugin's devcontainer MCP gateway slot in okf-mcp-server's .devcontainer/devcontainer.json (MCP_GATEWAY_HOST/TOKEN + NO_PROXY host.docker.internal), and add okf-mcp-server/.mcp.json pointing at the host okf-mcp-gateway using the dual-mode url convention.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 .devcontainer/devcontainer.json carries MCP_GATEWAY_HOST/TOKEN and NO_PROXY host.docker.internal
- [x] #2 .mcp.json points at the host okf gateway with a dual-mode url and a bearer token
- [ ] #3 the update is merged to master
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan:
1. .devcontainer/devcontainer.json — add MCP_GATEWAY_HOST=host.docker.internal + MCP_GATEWAY_TOKEN=${localEnv:MCP_GATEWAY_TOKEN} to containerEnv; append host.docker.internal to NO_PROXY (adopt current ralph 0.2.2 template slot). [AC#1]
2. Create repo-root .mcp.json with the ralph dual-mode convention: url http://${MCP_GATEWAY_HOST:-localhost}:8080/acme/mcp (localhost on host, host.docker.internal in-container) + Authorization: Bearer ${MCP_GATEWAY_TOKEN}. Owner 'acme' matches servers.yaml/README example. [AC#2]
3. Reconcile README 'Point a consumer at it' example to the dual-mode convention (was hardcoded host.docker.internal + OKF_GATEWAY_TOKEN) so committed .mcp.json and docs agree.
4. Validate: strict-JSON parse .mcp.json; JSONC parse devcontainer.json; run mypy+ruff+pytest (config-only, expect green).
5. task-reviewer on git diff master..HEAD; then Done + merge. [AC#3]
<!-- SECTION:NOTES:END -->
