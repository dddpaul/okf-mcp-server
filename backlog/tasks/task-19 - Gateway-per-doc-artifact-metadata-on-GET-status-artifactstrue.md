---
id: TASK-19
title: Gateway per-doc artifact metadata on GET /status?artifacts=true
status: Done
assignee: []
created_date: '2026-08-21 06:26'
updated_date: '2026-08-21 06:43'
labels:
  - 'feature:okf-knowledge-freshness'
dependencies: []
priority: medium
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Direction:** Additive per-doc artifact-metadata array on the existing `GET /status` surface, gated by `?artifacts=true` (producer surfaces truth, consumer passes through). No new endpoint. Resolves gap #1: a `knowledge://owner/type/id` ref today exposes no type/summary/path, so a mesh consumer cannot tell what the artifact IS.

**Locked decisions (with rationale):**
- **Metadata home = per-doc `artifacts:` list under each owner on `/status`.** *Rationale:* a mesh ref names an individual doc, so metadata must be per-doc; riding `/status` needs no new contract for control-gateway's `query_knowledge` to pass through.
- **`path` = repo-relative to the checkout root; `size` = `len(content)` bytes.** *Rationale:* the absolute checkout path leaks internal FS layout and is meaningless remotely; repo-relative is what a consumer/human can act on. Requires storing the relative path on `ParsedDoc` (today the path reaches `_build_doc` and is discarded).
- **Artifacts list gated behind `/status?artifacts=true`.** *Rationale:* keeps default `/status` a lean, backward-compatible health probe; the heavy per-doc inventory is opt-in. Mirror the existing `?format=` query-param handling on `/config`.
- **Fields per artifact: `{uri, id, type, title, summary, path, size, content_hash}`.** *Rationale:* every field except `path`/`size` already exists on `ParsedDoc`; `summary` = the existing `description`.

**Scope cuts:**
- No per-doc freshness (that is a per-owner signal — separate task; the per-doc change signal is `content_hash`).
- Default `/status` payload unchanged — artifacts appear ONLY with `?artifacts=true`.
- Stdio path (`run()`/`serve_stdio`/`cli.py`) and its 82 tests remain untouched and green; `ParsedDoc` changes are additive.

**Acceptance criteria (sketch):**
- `GET /status?artifacts=true` returns, per owner, an `artifacts` array of `{uri, id, type, title, summary, path, size, content_hash}`.
- `path` is repo-relative to the checkout root; `size == len(content)`; `summary` is the doc `description`.
- `GET /status` (no query param) is byte-for-byte unchanged — no `artifacts` key present.
- `ParsedDoc` carries the repo-relative path additively; existing stdio tests still green.
- `uv run mypy . && uv run ruff check .` clean; `uv run pytest` green including the 82 stdio tests.

**Implementation checklist:**
- Add a repo-relative `path` field to `ParsedDoc` (`src/okf_mcp_server/server.py`); set it in `_build_doc` from the file path relative to the scan root (thread the root through `load_docs`/`_iter_markdown_files` as needed); expose `size` as `len(content)` (property or field).
- In `_owner_status` (`src/okf_mcp_server/gateway/app.py`, ~line 262), parse `?artifacts=true` (mirror `/config`'s `?format=` handling) and, when set, add an `artifacts` array built from each owner's `cache.docs` (`uri`, `id`, `type`, `title`, `summary=description`, `path`, `size`, `content_hash`).
- Tests: Starlette TestClient over a `file://` bare-repo fixture asserting the array shape, repo-relative paths, sizes, `summary==description`, and that a plain `GET /status` omits the key.
- Run `uv run mypy . && uv run ruff check . && uv run pytest`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 GET /status?artifacts=true returns, per owner, an artifacts array of {uri, id, type, title, summary, path, size, content_hash}
- [x] #2 path is repo-relative to the checkout root
- [x] #3 size == len(content) for each artifact
- [x] #4 summary equals the doc description
- [x] #5 GET /status with no query param is byte-for-byte unchanged (no artifacts key present)
- [x] #6 ParsedDoc carries the repo-relative path additively; existing 82 stdio tests still green
- [x] #7 uv run mypy . && uv run ruff check . clean; uv run pytest green
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: (1) server.py — add defaulted `path: str = ""` field to ParsedDoc (additive; all 9 existing kwarg constructions stay valid) + `size` property = len(content); thread the scan `root` into _build_doc and set path = file_path.relative_to(root).as_posix(). Gateway _scan_docs passes roots=(checkout,), so scan root === checkout root => the path is repo-relative there. (2) gateway/app.py — _owner_status(owners, *, artifacts=False) grows a per-owner `artifacts` array built from cache.docs; the /status route parses ?artifacts= with a true/false allowlist and 400s otherwise, mirroring /config's ?format= handling. Default (no param) payload is untouched. (3) tests in test_gateway_status.py over the file:// bare-repo fixture: array shape, repo-relative paths, size==len(content), summary==description, key absent by default, yaml parity, 400 on a bad value. (4) README /status section documents the opt-in.

Commit: `03ef63f` - task-19: per-doc artifact metadata on GET /status?artifacts=true

Commit: `bf58abc` - task-19: document size as a character count and fix README cross-reference

Done. GET /status?artifacts=true adds a per-owner `artifacts` array of {uri,id,type,title,summary,path,size,content_hash}, built from the already-loaded ParsedDocs (pure in-memory read, no git/FS access). Default /status is untouched — the pre-existing exact-key-set assertion in test_status_default_json_shape_and_summary is the regression guard, plus a new byte-for-byte default==?artifacts=false comparison under injected clocks. ?artifacts= is allowlist-validated (true/false, else 400) mirroring /config's ?format=, so a typo fails loudly instead of silently omitting the inventory. ParsedDoc gained a defaulted trailing `path` field (repo-relative, POSIX-slashed, set in _build_doc from the scan root) and a `size` property; both additive — size is a property, not a field, so existing __eq__/__hash__ semantics are unchanged and all pre-existing kwarg constructions still compile. Gate: mypy clean, ruff clean, 188 passed / 1 skipped (master baseline 178; +10 new tests, zero regressions); the 82 stdio tests (test_server 36 + test_config 24 + test_linter 22) all green. Verified end-to-end by driving the real ASGI app against a file:// bare repo — nested path rendered as design/nested/adr.md, ?artifacts=yes returned 400. Review: task-reviewer agent is unregistered in this session's .claude config, so an independent substitute reviewer ran the full charter — APPROVED, no blockers/majors, two minor doc findings both fixed in bf58abc (README 'see the next section' pointed at Offline fallback rather than Freshness signals; `size` documentation overclaimed that characters and bytes coincide — this repo's own served docs carry 257 non-ASCII chars, under-reporting by up to 184 bytes on one file). DECISION: size == len(content) per AC#3 verbatim, i.e. a CHARACTER count, despite the task prose saying 'bytes'; the AC's exact equality is the contract, and the character/byte gap is now documented in both the property docstring and the README table. NOTE (out of scope): backlog doc-1 'HTTP Gateway Overview' lists routes as /{owner}/mcp, POST /{owner}/refresh, GET /healthz — it predates /status and /config entirely and was not updated here; documenting ?artifacts=true there without first adding /status itself would be inconsistent.
<!-- SECTION:NOTES:END -->
