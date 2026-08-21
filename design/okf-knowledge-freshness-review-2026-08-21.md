# Feature Review: okf-knowledge-freshness

**Verdict: Aligned**

**Date:** 2026-08-21
**In-scope tasks:** TASK-19, TASK-20
**Diff range:** `1b86a2ccd61678d23763bab34eefd6d63d78608a..HEAD`
**Design docs:** `design/okf-knowledge-freshness-brainstorm.md` (no PRD — feature was deliberately not PRD-shaped; the brainstorm's "Distilled for ralph-task" block is the authoritative hand-off)

**Passes run:** 3 (Brainstorm Scope Cuts), 5 (Out-of-Scope Creep), plus an adapted Pass 1 (Intent→Implementation built from the brainstorm's locked decisions + task ACs) and an adapted Pass 4 (Success-Metric assessment against the feature's stated goals).

**Passes skipped / adapted:** Passes 1, 2, and 4 have no formal `design/<name>-prd.md` to key against — this feature was deliberately *not* PRD-shaped. They were run against the brainstorm's **locked decisions**, **acceptance criteria**, and **scope cuts** instead, which serve the same normative role. Pass 2 (Non-Goals) is folded into Pass 3, since the "non-goals" live in the brainstorm's "Scope cuts" section.

**Provenance caveat:** the two `design/*.md` files the feature traces to (`okf-knowledge-freshness-brainstorm.md`, `okf-artifact-knowledge-freshness-semantics-intent.md`) are **untracked** in git. Only the tracked `doc-2` carries the normative content forward. This was a deliberate choice (TASK-20 notes), and it is fine, but the design intent itself is not version-controlled — worth knowing for any future audit.

## Intent → Implementation Matrix

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| LD-1 | Two additive changes to `GET /status` only; no new endpoint | **Delivered** | Diff touches only `_owner_status`/`create_app`'s `/status` route; no route added |
| LD-2 | Producer surfaces truth, consumer passes through | **Delivered** | Verdict computed at producer (`_freshness`); no consumer code in scope |
| 19-AC1 | `?artifacts=true` → per-owner `artifacts[]` of exactly `{uri,id,type,title,summary,path,size,content_hash}` | **Delivered** | `_artifact_entries` app.py:865; `test_...returns_per_doc_metadata` asserts `set(artifact)==ARTIFACT_KEYS` (those 8 exactly) |
| 19-AC2 | `path` repo-relative to checkout root | **Delivered** | `_build_doc` sets `path=path.relative_to(root).as_posix()` server.py:1166; test asserts `{"docs/reference.md","design/adr.md"}`, no abs prefix |
| 19-AC3 | `size == len(content)` | **Delivered** | `size` property = `len(self.content)`; test asserts `artifact["size"]==len(doc.content)` |
| 19-AC4 | `summary` = doc description | **Delivered** | `"summary": doc.description`; test asserts summary == fixture frontmatter description |
| 19-AC5 | Default `/status` byte-for-byte unchanged, no `artifacts` key | **Delivered (with designed nuance)** | `if artifacts:` gates the key; `test_status_omits_artifacts_by_default_and_when_explicitly_false` asserts `default.text == explicit_false.text`. See Reviewer Note 2 on the intended `freshness` addition |
| 19-AC6 | `ParsedDoc` carries `path` additively; stdio tests green | **Delivered** | `path: str = ""` defaulted trailing field; `size` a *property* (not field) so `__eq__`/`__hash__` unchanged |
| 20-AC1 | Every owner carries `freshness ∈ {fresh,stale_ttl,stale,unknown}`, with & without `?artifacts=true` | **Delivered** | `_owner_status` emits it unconditionally (app.py:1026); test asserts present in both renderings |
| 20-AC2-5 | Precedence by test: empty→`unknown`, source-down→`stale`, past-ttl→`stale_ttl`, within-ttl→`fresh` | **Delivered** | `test_status_freshness_covers_all_four_states_in_one_payload` drives all four in one payload on four owners |
| 20-AC6 | `freshness=="stale"` iff `stale==true` | **Delivered** | Both fed from one snapshot; asserts `(verdict=="stale") is entry["stale"]` on every read |
| 20-AC7 | Semantics doc via `backlog doc create` (states, transitions, serving-vs-source caveat, okf/control-gateway boundary) | **Delivered** | `backlog/docs/doc-2 - Owner-Freshness-Semantics.md` — all four sections present |
| 20-AC8 | mypy/ruff clean; pytest green incl. stdio | **Delivered** | Independently re-verified: mypy clean, ruff clean, 193 passed |

**Precedence exactness — CONFIRMED exact.** The live code is:
```
if commit is None:            return "unknown"
if not source_available:      return "stale"
if age_seconds is not None and age_seconds > ttl:  return "stale_ttl"
return "fresh"
```
- **Source-down outranks past-TTL:** the `not source_available` return precedes the age check — correct ordering. Pinned by `test_status_freshness_source_down_outranks_past_ttl_and_then_heals`, which walks `fresh→stale_ttl→stale→fresh` and asserts the offline owner reads `stale` even though its age is well past TTL.
- **`last_pulled is None` fallback:** `age_seconds is not None and …` means a `None` age falls straight through to `fresh` — exactly the brainstorm's "commit on hand + reachable source + no stamped age ⇒ fresh." Documented as defensive/unreachable in doc-2 §2.
- **Strict `>`:** age == ttl stays `fresh`; `test_...ttl_boundary_is_exclusive...` asserts age 60 → fresh, age 61 → stale_ttl at ttl=60.

## Non-Goal / Scope-Cut Violations

**None detected.** Every locked scope cut is respected:

- **No `git ls-remote` / source-ahead probe:** CONFIRMED. Grep of `_owner_status` for `subprocess|ls-remote|httpx|fetch|clone|socket` returns only docstring prose — the assembler is a pure in-memory read of `cache.*` primitives. `/status` stays network-free and offline-safe; `fresh` is documented as serving-freshness, not source-freshness (README + doc-2 §4).
- **No per-doc freshness:** CONFIRMED. `_artifact_entries` emits exactly 8 keys, none of them `freshness`; its docstring and doc-2 both state the deliberate absence, with `content_hash` as the per-doc change signal.
- **`freshness` on `/status` only — not `/refresh`, not MCP resource `_meta`:** CONFIRMED. The refresh route is untouched; `server.py`'s `read_resource`/`_meta` are outside the diff.
- **Artifacts gated behind `?artifacts=true`:** CONFIRMED, allowlist-validated (`true`/`false`, else `400`) mirroring `/config`'s `?format=`; `test_status_artifacts_rejects_an_unsupported_value` asserts `?artifacts=1 → 400`.
- **Consumer-side `query_knowledge` / okf:// pass-through out of scope:** CONFIRMED — no control-gateway code present.

## Scope Cut Violations (stdio path)

**None detected.** The stdio surface is intact:
- `cli.py`, `serve_stdio`, and `run()` are **not** in the diff at all.
- The only stdio-adjacent file touched is `server.py`, and purely **additively**: a defaulted trailing `path` field, a `size` *property*, and threading `root` through `_build_doc`/`load_docs`. `read_resource` behavior is unchanged.
- The four new `test_server.py` tests are additive. The "82 stdio tests" figure in the ACs is stale — TASK-19 added 4, so the stdio modules now collect ~90 and are all green. Additively-added tests are acceptable; no existing stdio behavior was modified.

## Success Metric Assessment

| Metric (implicit goal) | Status | Notes |
|--------|--------|-------|
| A `null` freshness beside a moved `served_commit` becomes structurally impossible | **Measurable — met** | `freshness` is always-on and always one of four defined states; membership asserted on every read |
| A bare `knowledge://owner/type/id` ref becomes resolvable to "what the artifact is" without a read | **Measurable — met** | `?artifacts=true` surfaces type/summary/path/size/content_hash from already-loaded docs |
| Default `/status` health-probe stays backward-compatible | **Measurable — mostly met (see nuance)** | Artifacts strictly opt-in and byte-verified. The feature *does* add exactly one always-on key, `freshness`, to default `/status` by design — additive, non-breaking (the existing `stale` boolean is retained) |
| Back-compat: `freshness=="stale"` ⟺ `stale==true` | **Measurable — met, by construction** | Both derived from one snapshot; asserted on every read across all owner states |
| Precedence correctness under adversarial states | **Measurable — met** | Notes report mutation testing: swapping stale/stale_ttl, swapping unknown/stale, `>`→`>=`, and "source-down only counts when past TTL" each fail a distinct test |

## Drift List

**No drift detected.** Every hunk traces to a requirement:
- `app.py` — `_artifact_entries` (TASK-19), `_freshness` (TASK-20), `_owner_status` wiring, `/status` route param parsing.
- `server.py` — `path`/`size`/root-threading (TASK-19).
- `doc-2` (20-AC7), `README.md` (documents both features, in-scope), task files (backlog bookkeeping), tests.
- The one refactor worth naming — `_owner_status` hoisting `commit`/`source_available`/`age_seconds`/`docs` into locals and reading `served_commit`/`source_available`/`last_pulled_age_seconds` from them — is behavior-preserving (identical values, snapshot consistency) and directly supports the freshness computation so the verdict cannot contradict the primitives beside it. Supporting infrastructure for in-scope work, not creep.

## Reviewer Notes

1. **`size` — bytes vs characters: resolved correctly, not a defect.** The brainstorm prose repeatedly glossed `size = len(content)` as "bytes." In Python `len(str)` is a **character** count, so the prose's "bytes" was imprecise for non-ASCII content (this repo's own docs carry non-ASCII, under-counting bytes by up to ~184 on one file). The team resolved the tension the right way: honor the AC's *exact equality* (`size == len(content)` — the contract), keep the implementation as `len(self.content)`, and document the character/byte gap explicitly in both the `ParsedDoc.size` docstring and the README table (follow-up commit `bf58abc`). The code satisfies 19-AC3 verbatim; consumers are warned not to trust `size` for a `Content-Length`. No change needed.

2. **Default `/status` "byte-for-byte unchanged" — read it precisely.** The claim holds for the **artifacts gating**: with the param absent or `false`, the payload is byte-identical to before (verified by `default.text == explicit_false.text` and the exact-key-set shape test). But cumulatively across both tasks, default `/status` *does* gain exactly one always-on key, `freshness`, relative to the pre-feature baseline — this is the brainstorm's locked "always-on" decision, an additive non-breaking change, and the pre-existing shape test was correctly updated to include it. A consumer doing strict closed-schema validation on default `/status` would see the new key; anyone reading known keys is unaffected. Intended, documented, correct.

3. **`_freshness` TTL precision trade-off.** The comparison is `int(age) > ttl` against the whole-second age `/status` renders, so the payload never shows `last_pulled_age_seconds: 60` next to `stale_ttl` at `ttl:60`. This lags `OwnerCache._is_fresh`'s float `< ttl` gate by <1s. Documented in the `_freshness` docstring as display precision on a read that never pulls — a deliberate, sound choice, not a correctness gap.

4. **Test suite health.** Independently re-ran the gate: mypy clean, ruff clean, **193 passed**. The lone failure, `test_docker_packaging.py::test_docker_compose_config_validates`, is **environmental** — the `docker` CLI is unavailable in this sandbox (exit 125). The diff touches no Docker files; this is not a feature regression.

Overall: both tasks land the brainstorm's locked decisions faithfully, the freshness precedence is implemented and tested exactly as specified (including the two subtle ordering/fallback rules), every scope cut holds, and the one semantic wrinkle (`size` units) was caught and documented rather than shipped silently. **Aligned.**
