# okf-mcp-server

Reusable, read-only MCP server that exposes a repo's knowledge files (backlog docs, decisions, design notes) as MCP resources over stdio. **Files decide their own fate** via OKF-style frontmatter — no per-source config, no kind/glob registry. One package, one process per owner repo, automatic URI namespacing from the repo basename.

Status: 0.2.0 — frontmatter-driven OKF source format.

## What is this

`okf-mcp-server` ships a configurable MCP server (`Server` from the `mcp` SDK) and a CLI/Python entry point that:

- resolves `owner` from `git rev-parse --show-toplevel` basename (fallback to `cwd` basename with a stderr warning);
- resolves scan roots by precedence: `--roots <csv>` flag → `OKF_MCP_ROOTS` env (colon-separated, PATH-style) → built-in default `[design/, backlog/docs/, backlog/decisions/]`;
- recursively walks every root, parses frontmatter, and registers a file as an MCP resource **iff** `export: true` **and** `type` is non-empty (strict opt-in);
- serves `list_resources` and `read_resource` over stdio for any MCP-aware client (Claude Code, Cursor, etc.).

It is read-only — no `write_resource`, no hot-reload, no search tool.

## Frontmatter contract

Every exported file declares itself in its own frontmatter:

```yaml
---
type: "Architecture Decision"   # required for export; free-form, OKF-semantic; slugified into URI
title: Knowledge Mesh foundation
export: true                    # required; opt-in — absent or false → file is invisible
description: ...                # optional; falls back to first non-heading paragraph (≤ 500 chars)
id: decision-2                  # optional; falls back to filename-derived id
---
```

Fields are read as-is; no schema validation beyond the strict export gate.

## URI scheme

Every resource URI follows `knowledge://{owner}/{type-slug}/{id}`.

- `owner` — basename of the git toplevel (stable contract).
- `type-slug` — deterministic slug of frontmatter `type`: lowercase, non-alphanumeric runs collapsed to `-`, leading/trailing `-` trimmed (`"Architecture Decision"` → `architecture-decision`). **Mutable** — editing `type` changes the slug; consumers must not pin to it.
- `id` — frontmatter `id` if present; otherwise filename-derived: first whitespace-delimited token of the stem (`doc-7 - Partner-...md` → `doc-7`), or the full stem when no whitespace is present (`c8-saas-...-brainstorm.md` → `c8-saas-...-brainstorm`). **Stable** — this is the contract that consumers cite.

Per matched file, the resource carries: `uri`, `name` (frontmatter `title` or filename stem), `description` (frontmatter `description` or first non-heading paragraph, truncated to 500 chars), `mimeType: text/markdown`, and the full body (frontmatter stripped) as content.

## Scan roots

Roots are resolved relative to the **git toplevel**, not cwd. A non-existent root is skipped with a stderr warning, not a fatal error. Files outside any configured root (e.g. `presentations/`, `.git/`) are invisible.

Precedence:

| Source | Separator | Example |
| --- | --- | --- |
| `--roots` flag | `,` | `--roots design/,backlog/docs,backlog/decisions` |
| `OKF_MCP_ROOTS` env | `:` (PATH-style) | `OKF_MCP_ROOTS="design/:backlog/docs:backlog/decisions"` |
| built-in default | n/a | `design/`, `backlog/docs/`, `backlog/decisions/` |

The first non-empty source wins; lower precedence is ignored entirely (not merged).

## In-repo adoption (PEP 723 shim)

When the owner repo lives in the same workspace as this package, the shim resolves `okf-mcp-server` from a local path — no publish step required. One file in the owner repo:

`mcp/server.py`:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["okf-mcp-server"]
#
# [tool.uv.sources]
# okf-mcp-server = { path = "../okf-mcp-server" }
# ///
from okf_mcp_server import run

if __name__ == "__main__":
    run()
```

Run it:

```sh
uv run mcp/server.py
```

`uv` resolves the path source and installs deps on first run. Wire it into Claude Code via a project-level `.mcp.json` entry pointing at `uv run mcp/server.py`.

## Cross-repo adoption

When the owner repo lives in a different repo, install via git URL pinned to a release tag:

```sh
uv add 'okf-mcp-server @ git+https://example.invalid/okf-mcp-server.git@v0.2.0'
```

> The host above is a **placeholder** — replace it with the canonical remote once the repository is published. The package lives at the repository **root** (no `#subdirectory=` is needed). Pin by tag (e.g. `@v0.2.0`) for reproducible federation across owner repos.

The shim then drops the `[tool.uv.sources]` block:

```python
# /// script
# requires-python = ">=3.10"
# dependencies = ["okf-mcp-server"]
# ///
from okf_mcp_server import run

if __name__ == "__main__":
    run()
```

## Known limitations

- **Single-process per owner.** One running process serves exactly one git repo. Multi-owner federation is achieved by running one shim per owner; there is no built-in aggregator.
- **No hot-reload.** Roots are walked once at startup. Edits to source files require restarting the server.
- **OKF `index.md` / `log.md` are not special.** If they carry `export: true` + `type`, they become ordinary resources; otherwise invisible.
- **`type-slug` is not contractual.** Editing `type` will silently change the URI's middle segment. Cite resources by `id`.

## Linter

A companion CLI, `okf-mcp-lint`, enforces three frontmatter invariants over the same roots the server scans, so misconfigured files fail loud locally and in CI instead of silently disappearing from the served set.

| Check | Severity | Behaviour |
| --- | --- | --- |
| Duplicate `id` within owner | **error** | Non-zero exit; both file paths reported. |
| `export: true` with missing/empty `type` | **error** | Non-zero exit; file path reported. |
| Distinct `type` values that slugify to the same URI segment | **warning** | Zero exit; both type strings + slug reported. |

`id` derivation and `type-slug` derivation are imported directly from the server module (`extract_id`, `slugify_type`) — the linter never reimplements them, so a verdict from the linter implies the same outcome at server load time.

Run it from the owner repo (point `--directory` at your okf-mcp-server checkout, or run `okf-mcp-lint` directly once installed):

```sh
okf-mcp-lint
# or, with overrides:
okf-mcp-lint --roots design/,backlog/docs
```

`--roots` and `OKF_MCP_ROOTS` precedence matches the server CLI.

## Tests

Tests live in `tests/`. Run them from the repository root:

```sh
uv run pytest
```

`tests/fixtures/sample-project/` is the worked example used by the smoke / contract / protocol tests; `tests/conftest.py` copies it into a fresh tmp dir and `git init`s it so the resolver behaves as in a real owner repo.
