---
id: TASK-3
title: Upgrade Ralph infrastructure files to latest templates
status: Done
assignee: []
created_date: '2026-06-28 15:43'
updated_date: '2026-06-28 16:09'
labels: []
dependencies: []
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Run the ralph-init upgrade flow to bring this project's Ralph infrastructure files up to the latest template versions, preserving project-specific customizations (CLAUDE.md Project-Specific block, brainstorm-rules.md Project additions, settings.local.json custom permissions).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Outdated managed files (ralph.sh, git hooks, .claude/settings.json, .claude/hooks/, .claude/settings.local.json, .devcontainer/*) are updated to current templates or intentionally skipped
- [x] #2 CLAUDE.md generic section regenerated from template; ## Project-Specific block preserved verbatim
- [x] #3 .claude/brainstorm-rules.md Ralph-managed region regenerated; ## Project additions preserved verbatim
- [x] #4 settings.local.json narrow-rule verification (Step 3.10) passes
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Upgrade applied: ralph.sh synced to current template (dropped RALPH_IMPL bash-fallback; python-only orchestrator). settings.local.json overwritten + re-merged narrow rules (Bash(uv run:*) replaces old bash preflight/wait-heartbeat rules; utc-to-moscow.sh both forms retained); Step 3.10 verify PASS. All other managed files already current. Note: settings.local.json is gitignored, so only ralph.sh appears in git.

Commit: `7721df5` - task-3: sync ralph.sh to current template (python-only orchestrator shim)

Final gate green (ruff clean, mypy clean, 82 tests pass). task-reviewer APPROVED. Merging task-3-ralph-upgrade.
<!-- SECTION:NOTES:END -->
