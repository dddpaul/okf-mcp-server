---
id: TASK-15
title: Adopt the simplified plugin-only ralph.sh
status: Done
assignee: []
created_date: '2026-07-25 14:28'
updated_date: '2026-07-25 14:40'
labels: []
dependencies: []
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace the local ralph.sh orchestrator resolver with the simplified upstream shim: keep only the $RALPH_ORCHESTRATOR override and the newest plugin-cache resolution plus the clear install-the-plugin error; remove the in-repo-source and legacy ~/.claude/skills tiers.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 okf-mcp-server/ralph.sh matches the simplified upstream resolver (tiers 1 and 4 only)
- [x] #2 No legacy resolution tiers remain in okf-mcp-server/ralph.sh
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: Simplify ralph.sh resolve_orchestrator() to the plugin-only upstream shim.
- Keep Tier 1 ($RALPH_ORCHESTRATOR explicit override) and Tier 4 (newest marketplace plugin-cache install via <cfg>/plugins/cache/*/ralph/*/.../ralph_orchestrator.py, sort -V | tail -1).
- Keep the clear 'install the plugin' error branch.
- Remove Tier 2 (in-repo plugin source) and Tier 3 (legacy ~/.claude/skills install).
- Rewrite the header comment: it currently claims a 5-tier precedence; update to the 2-tier (override + plugin-cache) model.
- PRESERVE 'export RALPH_PROJECT_ROOT': ralph_orchestrator.py resolve_project_root() reads it (fallback is the script dir, which under a plugin-cache install points into the cache, not the project). Dropping it would break detached nohup runs. It is no longer referenced inside the shim after Tier 2 is gone, but must stay exported for the orchestrator.
- Verify: bash -n ralph.sh; functional test of both tiers via a temp fake orchestrator + RALPH_ORCHESTRATOR override; full uv run mypy/ruff/pytest to confirm no Python regression.

Commit: `4f0f938` - task-15: simplify ralph.sh to plugin-only resolver (override + newest plugin-cache tiers, drop in-repo + legacy skills tiers)

Done: ralph.sh reduced from a 5-tier resolver to the plugin-only shim. Kept Tier 1 ($RALPH_ORCHESTRATOR override) and the newest plugin-cache install (former Tier 4, sort -V | tail -1) + the clear install-the-plugin error; removed the in-repo-source and legacy ~/.claude/skills tiers. resolve_orchestrator() body is byte-identical to the upstream reference ralph.sh (confirmed by task-reviewer). export RALPH_PROJECT_ROOT retained (orchestrator's resolve_project_root() reads it; its Path(__file__).parent fallback points into the plugin cache under a cache install, so detached nohup runs need the env var) and now carries an explanatory comment. Verified: bash -n + shellcheck clean; functional harness 5/5 (override tier, newest plugin-cache selection, precedence, error exit 1, legacy layout ignored); mypy + ruff clean; pytest 166 passed (docker-compose test deselected — pre-existing environmental failure on master, no 'docker compose' subcommand in sandbox, diff touches nothing Docker). task-reviewer verdict: APPROVED. Net -12 lines (8 insertions / 20 deletions).
<!-- SECTION:NOTES:END -->
