---
id: TASK-14
title: Expose served-commit and content-hash for freshness verification
status: Done
assignee: []
created_date: '2026-07-21 08:41'
updated_date: '2026-07-23 21:25'
labels: []
dependencies: []
priority: medium
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

A downstream cross-project orchestrator (planned in the stacks repo, decision-3) needs to verify that an upstream project's canon is actually fresh before releasing dependent work. Two independent freshness signals are required and this server is the single read-plane that can expose them: (1) **provenance** — which commit produced what is being served, so the orchestrator can check `served_commit ⊇ merge_commit` (the merged commit is an ancestor of what the gateway serves), confirming the whole merge→push→pull chain ran; (2) **content identity** — a stable hash of the served artifact, so the orchestrator can detect a no-op wake (upstream merged, but the specific artifact a downstream depends on is byte-identical → do not re-run downstream) and support content-pinned dependencies. Commit answers 'where did this come from?'; hash answers 'is this the artifact I need?'. Today the gateway serves git-sourced owners but exposes neither signal.

## Scope

In scope:
- Expose `served_commit` (the git SHA of the currently-served working copy) per owner, surfaced through the existing per-owner status endpoint.
- Expose `content_hash` (deterministic hash over the served bytes) per exported resource, surfaced through resource read/list metadata.
- Make `served_commit` update after `POST /{owner}/refresh`; keep `content_hash` stable for unchanged content.
- Document both fields and their distinct meaning (provenance vs content identity) in README.

Out of scope:
- The downstream verification logic itself — `served_commit ⊇ merge_commit` ancestor check, the cross-project dependency DAG, and the no-op-wake reaction all live in the stacks orchestrator (decision-3), NOT here. This server only EXPOSES the two signals.
- Any write/search/hot-reload capability — the server stays strictly read-only.

## Files

- `src/okf_mcp_server/gateway/owner_cache.py` (exists) — per-owner pull-on-demand cache; natural home for tracking the served commit SHA.
- `src/okf_mcp_server/gateway/git_source.py` (exists) — git pull/rev-parse; source of the served_commit value.
- `src/okf_mcp_server/gateway/app.py` (exists) — HTTP endpoints incl. per-owner /status; add served_commit to the per-owner state.
- `src/okf_mcp_server/server.py` (exists) — resource registration/read; compute and attach content_hash to resource metadata.
- `tests/test_gateway_status.py` (exists) — extend for served_commit; add/adjust tests for content_hash stability.
- `README.md` (exists) — document served_commit + content_hash semantics.

## Source

Source: /Users/paul/Private/Alfa/Projects/standard/stacks@88529056d679
Source design docs (read-only context, do NOT modify): /Users/paul/Private/Alfa/Projects/standard/stacks/backlog/decisions/decision-3 - Orchestration-Mesh-foundation.md (§ Кросс-проектные зависимости, § Отложенные механизмы — content_hash split); /Users/paul/Private/Alfa/Projects/standard/stacks/design/orchestrator-adr-grounding-audit.md

## Before starting (destination Claude validation checklist)

Before running this task, verify:
1. All (exists) file paths in the Files section still exist in this repo.
2. Each AC is objectively pass/fail (a pytest, curl against /status, or grep of README — not 'works correctly').
3. All dependencies in the task's frontmatter are status=Done (none declared).
4. Out-of-scope items are not accidentally pulled in — this server only exposes the signals; it does NOT implement the downstream ancestor-check or DAG.

If anything is unclear or any check fails: STOP and ask the user. Do NOT start work blindly.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 GET /{owner}/status response includes served_commit — the git commit SHA of the working copy the gateway currently serves for that owner (sourced from owner_cache/git_source); verified in tests/test_gateway_status.py
- [x] #2 Each exported MCP resource exposes a content_hash — a deterministic hash (e.g. sha256) over the served resource bytes — available via read_resource result metadata and/or list_resources; verified in a pytest
- [x] #3 After POST /{owner}/refresh advances the owner working copy to a new commit, served_commit reflects the new SHA (liveness/provenance signal); covered by a test
- [x] #4 content_hash is stable across a refresh that does not change a file's bytes — identical content yields identical hash (enables no-op-wake detection); covered by a test
- [x] #5 README documents served_commit (owner-level git provenance) and content_hash (resource-level, computed over the served representation), stating they answer different questions: provenance vs content identity
- [x] #6 uv run pytest is green; uv run mypy . && uv run ruff check . pass
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: (1) server.py — add ParsedDoc.content_hash property (sha256 over served UTF-8 content, 'sha256:<hex>'); attach content_hash to each Resource _meta in list_resources; switch read_resource from deprecated str return to Iterable[ReadResourceContents] carrying meta={content_hash} (also removes DeprecationWarning). (2) app.py _owner_status — rename surfaced key 'commit' -> 'served_commit' (provenance signal; single self-documenting field, no redundant duplicate); /refresh keeps 'commit' as an action-result field. (3) README — update /status section to served_commit + document resource content_hash, stating provenance-vs-identity distinction. (4) tests — extend test_gateway_status.py (served_commit key + refresh advances it) and test_server.py (content_hash present, deterministic, stable across identical bytes). Handoff checklist verdict: GREEN (all files exist, all AC objectively testable, no deps, downstream ancestor-check/DAG out of scope).

Commit: `539b15e` - task-14: expose served_commit on /status and per-resource content_hash in resource _meta

Done. Implemented: (1) ParsedDoc.content_hash property = 'sha256:'+sha256(content.utf-8) — purely content-addressed over the exact bytes read_resource returns. (2) list_resources + read_resource now surface content_hash in each resource's MCP _meta; read_resource switched from a deprecated bare-str return to Iterable[ReadResourceContents] (also removes the SDK DeprecationWarning) while preserving the served body text. (3) /status per-owner key renamed commit->served_commit (single self-documenting provenance field, no redundant duplicate); POST /{owner}/refresh keeps its own 'commit' action-result key (out of scope to rename). (4) README 'Freshness signals' section documents served_commit (provenance: where did this come from) vs content_hash (content identity: is this the artifact I need), disclaiming the downstream ancestor-check/DAG stays in the consumer. Tests: extended test_gateway_status.py (served_commit key + refresh advances served_commit while an unchanged doc's content_hash stays stable and a changed doc's differs) and test_server.py (content_hash determinism/content-addressing + _meta exposure on list & read). Gate: 166 passed/1 skipped, mypy clean (28 files), ruff clean. Review: task-reviewer APPROVED. Handoff checklist verdict was GREEN.
<!-- SECTION:NOTES:END -->
