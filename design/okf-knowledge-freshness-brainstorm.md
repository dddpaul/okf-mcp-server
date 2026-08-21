# okf-knowledge-freshness: artifact metadata surface + freshness semantics

Source design intent: `design/okf-artifact-knowledge-freshness-semantics-intent.md`
(spooled from live mesh testing). Primary design home: okf-mcp-server (producer /
executor). control-gateway is consumer-only — its `query_knowledge` pass-through is
covered by a sibling intent and is out of scope here.

## Architecture decision

Two **additive** changes to the existing `GET /status` surface, nothing else — no new
endpoint, no new contract. The guiding principle mirrors the rest of the gateway:
**the producer surfaces truth; the consumer passes it through** and never re-derives.

1. **Artifact metadata (gap #1):** under `/status?artifacts=true`, each owner gains a
   per-doc `artifacts:` array so a `knowledge://owner/type/id` ref can be resolved to
   *what the artifact is* (type / summary / path / size / content-hash) without a read.
2. **Freshness verdict (gap #2):** each owner gains an always-on `freshness` enum
   (`fresh` | `stale_ttl` | `stale` | `unknown`) computed authoritatively at the
   producer from primitives it already tracks, plus a normative semantics doc. This
   eliminates the observed bug where a consumer saw a moved `served_commit` but a
   `null` freshness — the producer now always emits one of four defined states.

## Components / flows

- **`ParsedDoc` (`src/okf_mcp_server/server.py`)** — gains a stored **repo-relative
  path** (today the path reaches `_build_doc` and is discarded) and a **`size`**
  (`len(content)`). `type`, `title`, `description` (→ `summary`), `uri`, `id`,
  `content_hash` already exist.
- **`_owner_status` (`src/okf_mcp_server/gateway/app.py:262`)** — the pure, side-effect-free
  `/status` assembler. Gains:
  - a per-owner `freshness` string (always on), computed by the precedence below;
  - a per-owner `artifacts:` array, included **only** when the request carries
    `?artifacts=true` (query-param parsing follows the existing `?format=` pattern on
    `/config`). Default `/status` stays byte-for-byte unchanged.
- **`OwnerCache` primitives (`src/okf_mcp_server/gateway/owner_cache.py`)** — already
  expose everything the enum needs: `commit`, `source_available`, `last_pulled`
  (monotonic, → `last_pulled_age_seconds`), and `resolved.ttl`. No cache changes.
- **Freshness-semantics doc** — created via `backlog doc create` so it is discoverable
  through `backlog doc list` (a project knowledge source named in CLAUDE.md) and travels
  with the repo for the sibling control-gateway intent to reference.

### Freshness precedence (authoritative, producer-computed)

```
commit is None                     -> unknown     (never loaded: loading or failed-empty)
elif source_available is False     -> stale       (offline fallback; TASK-17 last-good path)
elif last_pulled_age_seconds > ttl -> stale_ttl   (source reachable, refresh due next request)
else                               -> fresh       (served the last successful pull, within TTL)
```

Precedence rationale: a source-down checkout can also be past-TTL, but "refresh due" is
meaningless when the source is unreachable, so `stale` outranks `stale_ttl`. If age is
unknown (`last_pulled is None`) but a commit and reachable source exist, fall back to
`fresh` (source up, content on hand).

### State transitions (for the semantics doc)

- `unknown -> fresh` — first successful load/pull sets `commit` + `last_pulled` +
  `source_available=True`.
- `fresh -> stale_ttl` — no state write; the monotonic clock crosses `ttl`. `/status` is
  a passive read that does **not** refresh, so it can show `stale_ttl`; the next real MCP
  request re-pulls and it self-clears.
- `stale_ttl -> fresh` — a `get_or_refresh`/`force_refresh` pull updates `last_pulled`.
- `fresh|stale_ttl -> stale` — a pull attempt fails; `source_available` flips `False`,
  `commit` retained (serving last-good).
- `stale -> fresh` — a later pull attempt succeeds; `source_available` flips `True`,
  `last_pulled` updated.

### Producer / consumer boundary (for the doc)

okf-mcp-server owns exactly `{fresh, stale_ttl, stale, unknown}` — **serving-freshness**:
"is what I serve current as of my last successful source contact, within TTL." It is
**not** source-freshness — `fresh` does **not** claim the source has not advanced since the
last pull (that would need a network probe okf deliberately does not make on `/status`).
Mesh/goal concepts such as `blocked_upstream` are **derived by control-gateway** from
`unknown`/`stale`; okf never emits them.

## Scope cuts

- **No `git ls-remote` source-ahead probe.** `freshness` stays a pure rollup of local
  primitives so `/status` remains network-free and offline-safe. `fresh` therefore means
  serving-freshness, not source-freshness (documented explicitly).
- **No per-doc freshness.** Every doc in an owner shares one checkout, so per-doc freshness
  would be identical; the per-doc change signal is the existing `content_hash`.
- **`freshness` on `/status` only** — not on `POST /{owner}/refresh` and not in MCP
  resource `_meta` for now (YAGNI).
- **Artifacts list is gated** behind `?artifacts=true`; the default `/status` payload does
  not grow, so existing health-probe consumers are unaffected.
- **Consumer-side `query_knowledge` / okf:// pass-through is out of scope** — control-gateway
  sibling intent.
- **Existing stdio path and its 82 tests remain untouched and green.** `ParsedDoc` changes
  are additive (new fields); `read_resource` / `load_docs` behavior is preserved.

## Open questions

- Slug: this brainstorm uses `okf-knowledge-freshness` (shorter than the intent-doc stem
  `okf-artifact-knowledge-freshness-semantics`). The `feature:okf-knowledge-freshness`
  label is what `/ralph-review` will resolve against.
- Whether control-gateway should later cache/pin the per-doc `content_hash` for change
  detection — deferred to the sibling intent.

## Hand-off

Next: `ralph-task` with `feature=okf-knowledge-freshness` to create the two tasks below.
Not PRD-shaped (two small, mostly-independent additive changes to one endpoint; no heavy
cross-task contract), so the per-task distillation below is the authoritative hand-off —
the brainstorm file itself is never opened by the implementer.

## Distilled for ralph-task

**Direction:** Two additive changes to `GET /status` in okf-mcp-server (producer surfaces
truth, consumer passes through): (1) a gated per-doc artifact-metadata array; (2) an
always-on per-owner `freshness` enum plus a normative semantics doc. No new endpoint, no
network on `/status`, stdio path untouched.

**Locked decisions (with rationale):**
- **Metadata home = per-doc `artifacts:` list on `/status`.** *Rationale:* a mesh ref names
  an individual doc, so metadata must be per-doc; riding `/status` needs no new contract for
  control-gateway's `query_knowledge` to pass through.
- **`path` = repo-relative, plus `size` = `len(content)` bytes.** *Rationale:* the absolute
  checkout path leaks internal FS layout and is meaningless remotely; repo-relative is what a
  consumer/human can act on. Requires storing the relative path on `ParsedDoc` (today discarded).
- **Artifacts list gated behind `/status?artifacts=true`.** *Rationale:* keeps default `/status`
  a lean, backward-compatible health probe; the heavy per-doc inventory is opt-in.
- **Producer emits an explicit `freshness` enum (not primitives-only).** *Rationale:* a verdict
  with no authoritative owner is exactly why consumers produced `null` next to a moved commit;
  one producer-computed source makes that impossible.
- **Four states `fresh | stale_ttl | stale | unknown` with fixed precedence** (unknown if no
  commit; else stale if source down; else stale_ttl if past TTL; else fresh). *Rationale:*
  source-down outranks past-TTL because "refresh due" is meaningless when the source is
  unreachable.
- **`freshness` is per-owner and always-on; per-doc freshness is NOT emitted.** *Rationale:* a
  health poll must see the verdict without the heavy list; all docs in an owner share one
  checkout so per-doc freshness is redundant (`content_hash` is the per-doc signal).
- **TTL stays the refresh throttle, surfaced in the enum only as `stale_ttl`.** *Rationale:*
  `freshness` is about source-reachability; the single past-TTL state makes "refresh due"
  visible on the passive `/status` read without coupling the whole enum to age.
- **Existing `stale` boolean retained for back-compat** (`freshness=stale` ⟺ `stale=true`).
  *Rationale:* additive, non-breaking for current `/status` consumers.
- **Semantics doc created via `backlog doc create`.** *Rationale:* discoverable via
  `backlog doc list` (a CLAUDE.md knowledge source) and travels with the repo for the sibling
  control-gateway intent.

**Scope cuts:**
- No `git ls-remote` / source-ahead probe; `/status` stays network-free (serving-freshness, not
  source-freshness).
- No per-doc freshness; no `freshness` on `/refresh` or in MCP resource `_meta`.
- Default `/status` payload unchanged (artifacts gated).
- Consumer-side `query_knowledge` / okf:// wiring out of scope (control-gateway sibling intent).
- Stdio `run()` / `serve_stdio` / `cli.py` and the 82 stdio tests untouched.

**Acceptance criteria (sketch):**
- TASK A (artifacts): `GET /status?artifacts=true` returns, per owner, an `artifacts` array of
  `{uri, id, type, title, summary, path, size, content_hash}`; `path` is repo-relative to the
  checkout root; `size == len(content)`; `summary` is the doc `description`.
- TASK A: `GET /status` (no query param) is byte-for-byte unchanged — no `artifacts` key present.
- TASK A: `ParsedDoc` carries the repo-relative path additively; stdio tests still green.
- TASK B (freshness): every owner entry on `/status` (with and without `?artifacts=true`) carries
  a `freshness` field ∈ {`fresh`,`stale_ttl`,`stale`,`unknown`}.
- TASK B: precedence verified by test — empty volume ⇒ `unknown`; source-down healthy checkout ⇒
  `stale`; injected clock advanced past `ttl` ⇒ `stale_ttl`; fresh pull within TTL ⇒ `fresh`.
- TASK B: `freshness=stale` iff the existing `stale` boolean is `true` (back-compat holds).
- TASK B: a semantics doc exists (via `backlog doc create`) defining the four states, their
  transitions, the serving-vs-source-freshness caveat, and the okf-owns / control-gateway-derives-
  `blocked_upstream` boundary.
- All tasks: `uv run mypy . && uv run ruff check .` clean; `uv run pytest` green including the 82
  stdio tests.

**Implementation checklist:**
- TASK A: add a repo-relative `path` field to `ParsedDoc`; set it in `_build_doc` from the file
  path relative to the scan root (thread the root through `load_docs`/`_iter_markdown_files` as
  needed); expose `size` as `len(content)` (property or field).
- TASK A: in `_owner_status`, parse `?artifacts=true` (mirror `/config`'s `?format=` handling) and,
  when set, add an `artifacts` array built from each owner's `cache.docs` (`uri`, `id`, `type`,
  `title`, `summary=description`, `path`, `size`, `content_hash`).
- TASK A: tests — TestClient over a `file://` bare-repo fixture asserting array shape, repo-relative
  paths, sizes, and that default `/status` omits the key.
- TASK B: in `_owner_status`, compute `freshness` per the precedence from `cache.commit`,
  `cache.source_available`, `last_pulled_age_seconds`, and `cache.resolved.ttl`; emit it always-on
  per owner; keep the existing `stale` boolean.
- TASK B: tests — force each state via fixture/clock injection and assert the enum, plus the
  `freshness=stale ⟺ stale=true` invariant.
- TASK B: write the semantics doc via `backlog doc create` (states, transition table, caveat,
  producer/consumer boundary); reference it from the gateway README `/status` description if trivial.
- All: run `uv run mypy . && uv run ruff check . && uv run pytest`.
