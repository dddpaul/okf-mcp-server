---
id: TASK-9
title: Sync CLAUDE.md to latest Ralph template (add Implementation Mode Gate)
status: Done
assignee: []
created_date: '2026-07-02 18:25'
updated_date: '2026-07-02 18:33'
labels:
  - ralph-infra
dependencies: []
priority: medium
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Read-only drift check found the CLAUDE.md generic section (above ## Project-Specific) is the only tracked managed file behind the current ralph-init template. The template adds a ## Implementation Mode Gate section (interactive run-mode selection: Ralph vs Interactive before implementing a task). Apply the ralph-init upgrade CLAUDE.md special-merge: regenerate the generic block from template, preserve the ## Project-Specific block verbatim. All other managed files are already current.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 CLAUDE.md generic section (all lines above ## Project-Specific) matches the current ralph-init template byte-for-byte, including the new ## Implementation Mode Gate section
- [x] #2 The ## Project-Specific block and everything below it is unchanged (project customizations preserved verbatim)
- [x] #3 No other managed Ralph file is modified by the upgrade (ralph.sh, git hooks, settings.json, .claude/hooks/*, brainstorm-rules managed region, devcontainer files remain current)
- [x] #4 A post-upgrade read-only drift re-check reports CLAUDE.md (generic) as current
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Commit: `fe37285` - task-9: sync CLAUDE.md generic block to latest template (add Implementation Mode Gate)

Applied ralph-init upgrade CLAUDE.md special-merge: regenerated generic block from template (adds ## Implementation Mode Gate), preserved ## Project-Specific verbatim. Only CLAUDE.md changed (+16 lines, 0 deletions). Quality gate green (mypy, ruff, 82 tests). task-reviewer APPROVED.
<!-- SECTION:NOTES:END -->
