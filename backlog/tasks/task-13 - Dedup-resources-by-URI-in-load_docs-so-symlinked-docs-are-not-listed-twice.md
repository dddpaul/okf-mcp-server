---
id: TASK-13
title: Dedup resources by URI in load_docs so symlinked docs are not listed twice
status: Done
assignee: []
created_date: '2026-07-17 14:46'
updated_date: '2026-07-17 15:08'
labels:
  - bug
dependencies: []
priority: medium
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
## Why

When the gateway serves an owner whose repo has a root-level `README.md`
symlink into `backlog/docs/` (the standard single-source-of-truth pattern that
GitHub requires), `resources/list` returns the same `knowledge://` URI twice.
The gateway scans the whole checkout root (`owner_cache.py` sets
`roots=(checkout,)`), so `rglob("*.md")` reaches both the canonical file and the
symlink pointing at it; `_iter_markdown_files` treats a symlink-to-file as a file
(`is_file()` follows symlinks), and `load_docs` appends every parsed doc without
deduplicating by URI. MCP resource URIs must be unique — a duplicated entry is
noise for every consumer and silently collapses in dict-keyed clients. The engine
must guarantee one resource per URI regardless of filesystem aliasing.

## Observed (live gateway, stacks owner)

`resources/list` for owner `stacks` returned `knowledge://stacks/readme/doc-1`
**twice** (all other docs once). `stacks` has exactly one root symlink:
`README.md -> backlog/docs/doc-1 - Project-overview.md`. The stdio shim path does
NOT reproduce it (default roots `design/`, `backlog/docs/`, `backlog/decisions/`
never scan the repo root); only the gateway's whole-checkout scan surfaces the
alias.

## Root-cause trace

1. `src/okf_mcp_server/gateway/owner_cache.py` (~line 236): `config =
   ServerConfig(owner=..., roots=(checkout,))` — scans the entire repo root.
2. `src/okf_mcp_server/server.py` `_iter_markdown_files` (~line 66):
   `sorted(p for p in root.rglob("*.md") if p.is_file())` — `is_file()` follows
   symlinks, so the root `README.md` symlink is yielded alongside its target.
3. `src/okf_mcp_server/server.py` `load_docs` (~line 94): appends each `ParsedDoc`
   with no dedup, so the same `ParsedDoc.uri` lands in the list twice.

## Scope

In scope:
- Make `load_docs` guarantee at most one `ParsedDoc` per distinct
  `ParsedDoc.uri` (`knowledge://{owner}/{type_slug}/{id}`). Either dedup by URI
  in `load_docs` and/or skip symlinks in `_iter_markdown_files`
  (`p.is_file() and not p.is_symlink()`) — implementer's choice, but the
  observable invariant (unique URIs) is what the AC pins.
- Add a regression test under `tests/` reproducing the gateway scenario
  (whole-root scan + a repo-root symlink into `backlog/docs/`).

Out of scope:
- Changing the gateway scan-root strategy (`roots=(checkout,)` → subroots). The
  fix belongs to the engine's uniqueness invariant, not to narrowing the scan.
- Removing or altering any owner's `README.md` symlink — it is a legitimate,
  required pattern the engine must tolerate.
- Any change to the `knowledge://` URI scheme or the `export:true` + `type:`
  frontmatter export gate.

## Files

- `src/okf_mcp_server/server.py` (exists) — `load_docs` (~L94) must dedup by URI;
  `_iter_markdown_files` (~L66) currently follows symlinks via `is_file()`.
- `src/okf_mcp_server/gateway/owner_cache.py` (exists) — context only: `roots=(checkout,)`
  (~L236) is what exposes the alias; do NOT change it as the fix.
- `tests/` (exists) — add the regression test here.

## Source

Source: /Users/paul/Private/Alfa/Projects/equation/core@06c790e7b84a
No source design doc — derived from a live MCP diagnostics session; full
reproduction is inlined above.

## Before starting (destination Claude validation checklist)

Before running this task, verify:
1. All `(exists)` file paths in the Files section still exist in this repo.
2. Each AC is objectively pass/fail (a pytest invocation or lint command — not
   "works correctly").
3. All dependencies in the task's frontmatter are status=Done (this task has none).
4. Out-of-scope items are not accidentally pulled in by ambiguous AC (do not
   touch the gateway scan roots or any owner symlink).

If anything is unclear or any check fails: STOP and ask the user. Do NOT start
work blindly.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 load_docs returns at most one ParsedDoc per distinct uri (knowledge://{owner}/{type_slug}/{id}); a new pytest asserts this against a scan root containing both a canonical .md and a symlink resolving to it
- [x] #2 A regression test under tests/ builds a temp repo with backlog/docs/doc-1*.md (export:true, type:readme, id:doc-1) plus a repo-root README.md symlink to it, runs load_docs with roots=(<repo-root>,), and asserts exactly one knowledge://<owner>/readme/doc-1 resource
- [x] #3 The single deduped resource still serves the document body: its content is non-empty and equals the canonical file's content (asserted in the regression test)
- [x] #4 uv run pytest passes
- [x] #5 uv run mypy . && uv run ruff check . passes
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: enforce unique knowledge:// URIs in load_docs. (1) _iter_markdown_files skips symlinks (p.is_file() and not p.is_symlink()) so the canonical file—not a repo-root README.md alias—is the one parsed (correct title/metadata). (2) load_docs dedups by ParsedDoc.uri, first occurrence wins, as the structural MCP unique-URI backstop robust to any aliasing. Add regression test: temp repo with backlog/docs/doc-1*.md (export:true,type:readme,id:doc-1) + repo-root README.md symlink to it, roots=(repo_root,), assert exactly one knowledge://stacks/readme/doc-1 whose content is non-empty and equals the canonical body. Do NOT change gateway roots=(checkout,) or any symlink.

Commit: `796328c` - task-13: dedup knowledge:// resources by URI in load_docs (skip symlinks)

Done. Fix: server.py load_docs dedups by ParsedDoc.uri (first-occurrence wins, set-backed) as the MCP unique-URI backstop; _iter_markdown_files now skips symlinks (p.is_file() and not p.is_symlink()) so the canonical file—not a repo-root README.md alias—is parsed (correct title/metadata). Regression test tests/test_server.py::test_load_docs_dedups_symlinked_doc_to_unique_uri reproduces the live stacks scenario (canonical backlog/docs/doc-1*.md + repo-root README.md symlink, roots=(repo,)) and asserts exactly one knowledge://stacks/readme/doc-1 whose content is non-empty and equals the canonical body; verified it fails (assert 2==1) without the fix. Gates: 162 passed/1 skipped, mypy clean, ruff clean. owner_cache.py roots=(checkout,) left untouched (out of scope). task-reviewer verdict: APPROVED.
<!-- SECTION:NOTES:END -->
