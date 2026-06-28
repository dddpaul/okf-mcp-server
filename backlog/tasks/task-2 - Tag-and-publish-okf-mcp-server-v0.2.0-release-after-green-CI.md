---
id: TASK-2
title: Tag and publish okf-mcp-server v0.2.0 release after green CI
status: To Do
assignee: []
created_date: '2026-06-28 10:11'
labels: []
dependencies: []
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Follow-up to TASK-1. The okf-mcp-server package import/rename is complete and merged, but the v0.2.0 release tag could not be created because this repository has no git remote, so GitHub Actions CI (.github/workflows/ci.yml) cannot run. This task covers publishing the repo to a remote, confirming CI is green, and tagging the release.

Blocked until: a git remote is configured for this repository.

Origin: AC #8 of TASK-1, deferred at merge time.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Repository has a git remote configured and the default branch is pushed
- [ ] #2 CI workflow runs on the remote and is green (ruff + mypy + pytest all pass)
- [ ] #3 Annotated tag v0.2.0 is created on the merge commit and pushed after CI is green
<!-- AC:END -->
