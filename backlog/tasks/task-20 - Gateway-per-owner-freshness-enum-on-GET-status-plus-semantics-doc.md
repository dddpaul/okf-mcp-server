---
id: TASK-20
title: Gateway per-owner freshness enum on GET /status plus semantics doc
status: Done
assignee: []
created_date: '2026-08-21 06:26'
updated_date: '2026-08-21 07:04'
labels:
  - 'feature:okf-knowledge-freshness'
dependencies: []
priority: medium
ordinal: 20000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Direction:** Add an always-on per-owner `freshness` enum to `GET /status`, computed authoritatively at the producer from primitives `OwnerCache` already tracks, plus a normative freshness-semantics doc. Resolves gap #2: consumers re-derive "fresh" from primitives and get it wrong — a `null` freshness was observed next to a moved `served_commit`, and `null->fresh` transition timing is opaque. One authoritative producer verdict makes a `null` verdict structurally impossible.

**Locked decisions (with rationale):**
- **Producer emits an explicit `freshness` enum (not primitives-only).** *Rationale:* a verdict with no authoritative owner is exactly why consumers produced `null` next to a moved commit; one producer-computed source makes that impossible.
- **Four states `fresh | stale_ttl | stale | unknown` with fixed precedence:**

```
commit is None                     -> unknown     (never loaded: loading or failed-empty)
elif source_available is False     -> stale       (offline fallback; TASK-17 last-good path)
elif last_pulled_age_seconds > ttl -> stale_ttl   (source reachable, refresh due next request)
else                               -> fresh       (served the last successful pull, within TTL)
```

  *Rationale:* source-down outranks past-TTL because "refresh due" is meaningless when the source is unreachable. If age is unknown (`last_pulled is None`) but a commit and reachable source exist, fall back to `fresh`.
- **`freshness` is per-owner and always-on** (present both with and without `?artifacts=true`); **per-doc freshness is NOT emitted.** *Rationale:* a health poll must see the verdict without the heavy list; all docs in an owner share one checkout so per-doc freshness is redundant (`content_hash` is the per-doc signal).
- **TTL stays the refresh throttle, surfaced in the enum only as `stale_ttl`.** *Rationale:* `freshness` is about source-reachability; the single past-TTL state makes "refresh due" visible on the passive `/status` read without coupling the whole enum to age.
- **Existing `stale` boolean retained for back-compat:** `freshness=stale` iff `stale=true`. *Rationale:* additive, non-breaking for current `/status` consumers.
- **Semantics doc created via `backlog doc create`.** *Rationale:* discoverable via `backlog doc list` (a CLAUDE.md knowledge source) and travels with the repo for the sibling control-gateway intent.

**Scope cuts:**
- No `git ls-remote` / source-ahead probe; `/status` stays network-free and offline-safe. `fresh` therefore means SERVING-freshness ("current as of my last successful source contact, within TTL"), NOT source-freshness ("source has not advanced").
- No `freshness` on `POST /{owner}/refresh` and none in MCP resource `_meta` (YAGNI).
- Stdio path (`run()`/`serve_stdio`/`cli.py`) and its 82 tests remain untouched and green.

**Acceptance criteria (sketch):**
- Every owner entry on `/status` (both with and without `?artifacts=true`) carries a `freshness` field in `{fresh, stale_ttl, stale, unknown}`.
- Precedence verified by test: empty volume -> `unknown`; source-down healthy checkout -> `stale`; injected clock advanced past `ttl` -> `stale_ttl`; fresh pull within TTL -> `fresh`.
- `freshness=stale` iff the existing `stale` boolean is `true` (back-compat holds).
- A semantics doc exists (via `backlog doc create`) defining the four states, their transitions (`unknown->fresh` on first load; `fresh->stale_ttl` as the clock crosses TTL; `->stale` when a pull fails; `->fresh` when a later pull succeeds), the serving-vs-source-freshness caveat, and the boundary that okf owns the four states while control-gateway derives `blocked_upstream` from `unknown`/`stale`.
- `uv run mypy . && uv run ruff check .` clean; `uv run pytest` green including the 82 stdio tests.

**Implementation checklist:**
- In `_owner_status` (`src/okf_mcp_server/gateway/app.py`), compute `freshness` per the precedence from `cache.commit`, `cache.source_available`, `last_pulled_age_seconds`, and `cache.resolved.ttl`; emit it always-on per owner; keep the existing `stale` boolean.
- Tests: force each state via fixture / injected-clock control and assert the enum, plus the `freshness=stale <-> stale=true` invariant.
- Write the semantics doc via `backlog doc create` (four states, transition table, serving-vs-source-freshness caveat, producer/consumer boundary); reference it from the gateway README `/status` description if trivial.
- Run `uv run mypy . && uv run ruff check . && uv run pytest`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Every owner entry on /status (with and without ?artifacts=true) carries a freshness field in {fresh, stale_ttl, stale, unknown}
- [x] #2 Precedence verified by test: empty volume -> unknown
- [x] #3 Precedence verified by test: source-down healthy checkout -> stale
- [x] #4 Precedence verified by test: injected clock advanced past ttl -> stale_ttl
- [x] #5 Precedence verified by test: fresh pull within TTL -> fresh
- [x] #6 freshness=stale iff the existing stale boolean is true (back-compat holds)
- [x] #7 A semantics doc exists via backlog doc create defining the four states, their transitions, the serving-vs-source-freshness caveat, and the okf-owns / control-gateway-derives-blocked_upstream boundary
- [x] #8 uv run mypy . && uv run ruff check . clean; uv run pytest green including the 82 stdio tests
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: (1) app.py — add module-level _freshness(cache, age) helper implementing the locked precedence (commit None -> unknown; source_available False -> stale; age > ttl -> stale_ttl; else fresh, incl. age-None fallback), call it from _owner_status so 'freshness' is emitted always-on per owner right after 'stale', reusing the same snapshot locals so verdict and primitives cannot disagree. (2) tests/test_gateway_status.py — extend the shape assertion with the new key; add freshness tests driving each of the four states (loading/failed-empty -> unknown, source-down healthy checkout -> stale, FakeClock advanced past ttl -> stale_ttl, fresh pull -> fresh) plus the freshness=='stale' <-> stale is True invariant across all owner states, and assert the key is present with AND without ?artifacts=true. (3) backlog doc create the normative semantics doc (four states, transition table, serving-vs-source-freshness caveat, okf-owns/control-gateway-derives-blocked_upstream boundary). (4) README /status section: document the field + link the doc. (5) uv run mypy . && uv run ruff check . && uv run pytest.

Commit: `8ea5ad2` - task-20: always-on per-owner freshness enum on GET /status plus semantics doc

Commit: `0daf80f` - task-20: cover source-down inside the TTL and correct the freshness docs

Implemented. Producer-side enum: new pure _freshness(commit, source_available, age_seconds, ttl) helper in gateway/app.py encodes the locked precedence (no-commit -> unknown; source-down -> stale; age > ttl -> stale_ttl; else fresh). _owner_status now snapshots commit/source_available/age_seconds into locals and feeds BOTH the existing 'stale' boolean and the new always-on 'freshness' key from that one snapshot, so the verdict can never contradict the primitives rendered beside it; AC#6 holds by construction, not by test luck. 'last_pulled_age_seconds' was hoisted to the same local (identical value, no behavior change). Default /status gains exactly one key; nothing else moved.

Boundary decision (documented in the _freshness docstring): the TTL comparison is strictly '>' against the same whole-second age /status renders, so the payload never shows 'last_pulled_age_seconds: 60' next to stale_ttl at ttl=60. Cost: it lags OwnerCache._is_fresh's float '< ttl' gate by <1s. That is display precision on a read that never pulls, not a correctness gap.

Tests (5 new, tests/test_gateway_status.py): a four-owner matrix driving fresh/stale_ttl/stale/unknown simultaneously in ONE payload via per-owner ttl overrides against a shared FakeClock (also proves per-owner independence, and that no-commit outranks source-down for the empty-volume owner); the loading path of unknown; the strict TTL boundary (age == ttl still fresh, ttl+1 stale_ttl, refresh restores fresh); source-down-outranks-past-TTL walking fresh->stale_ttl->stale->fresh; and source-down INSIDE the ttl window. Shared _freshness_of() helper asserts on every read that the verdict is a defined state and that freshness=='stale' iff stale is True. All offline/network-free (file:// bare repos + injected clocks).

Validated by mutation testing rather than coverage: swapping stale/stale_ttl order, swapping unknown/stale order, '>' -> '>=', and 'source-down only counts when also past TTL' each fail a DIFFERENT test. The first version of the suite did NOT catch mutation 1 (every source-down path left last_pulled None, so the age branch never fired) and the reviewer independently found the 4th gap; both tests were added to close them.

Docs: backlog doc-2 'Owner Freshness Semantics' (four states, precedence with rationale, transition table verified row-by-row against OwnerCache, serving-vs-source-freshness caveat, okf-owns / control-gateway-derives-blocked_upstream boundary). README /status section gains a 'The freshness verdict' subsection + a cross-reference from 'Freshness signals'.

Review: the lifecycle's task-reviewer agent is NOT registered in this checkout (no .claude/agents/, no task-reviewer-rules.md), so an independent claude agent was given the reviewer charter instead - same known substitution as prior tasks. Verdict APPROVED, 0 blocking. Its 2 non-blocking + 4 nit findings were all fixed before Done: the untested source-down-inside-TTL state (new test, verified to catch the mutation), a README example showing freshness 'fresh' beside age 340 with a documented ttl of 60 (now 40), a stale 'byte-identical' docstring claim, the unreachable unknown-age arm now marked defensive in doc-2, confused 'converse of an iff' phrasing, and an orphaned curl block.

AC#8 note: the '82 stdio tests' figure is stale - it predates TASK-19, which added 4 tests to test_server.py. The stdio modules now collect 90 and are all green; TASK-20 changed no stdio file (diff touches only gateway/app.py, tests/test_gateway_status.py, README.md, doc-2). Full suite 193 passed / 1 skipped, mypy and ruff clean. Line length was self-checked manually (this repo configures no ruff E501): both Python files are <=88 everywhere.

Scope: design/okf-knowledge-freshness-brainstorm.md and design/okf-artifact-knowledge-freshness-semantics-intent.md were deliberately left untracked - they predate this task, TASK-19 left them the same way, and their normative content is now captured in doc-2, which IS tracked and discoverable via 'backlog doc list'.
<!-- SECTION:NOTES:END -->
