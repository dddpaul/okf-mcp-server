# Feature Review: http-gateway (pre-implementation planning-coverage)

**Date:** 2026-07-02
**Type:** Pre-implementation planning review (TASK-4..8 all "To Do"; no code/diff exists).
**Verdict: Aligned**

Passes run: 1 (PRD Coverage → adapted to intent-to-task-coverage), 2 (Non-Goal
Protection), 3 (Brainstorm Scope Cuts), 4 (Success-Metric Realism). Pass 5
(out-of-scope creep in a diff) is N/A pre-implementation — no diff exists; AC
non-goal leakage audited instead. No custom rules file present.

Pipeline-hygiene warnings (non-blocking): TASK-4..8 each reference
`design/http-gateway-brainstorm.md` in their descriptions. This trips the
ralph-task "Distilled for ralph-task" contract scan. These are ralph-backlog
(PRD-derived) tasks that also carry the distilled shared contracts inline, so
the brainstorm pointer is supplementary context, not the sole source — lower
risk than a ralph-task-created task with the same reference.

---

## 1. Brainstorm → PRD fidelity

The PRD faithfully and completely captures every locked decision from the
brainstorm's "Distilled for ralph-task" block. No decision dropped, weakened, or
contradicted.

| Brainstorm locked decision | PRD carrier | Fidelity |
|---|---|---|
| Additive, not a refactor | Goal 6, FR-12, Tech Considerations "Reuse, don't fork" | Exact |
| Single multi-owner gateway, `/{owner}/mcp` | Goal 1, FR-1 | Exact |
| Git-sourced, no mounts | Goal 2, FR-2 | Exact |
| Docker `restart: unless-stopped` + idempotent `up -d` | Goal 5, FR-11 | Exact |
| Pull-on-demand + TTL (default 60s), `/refresh` force+webhook target | FR-7, FR-8 | Exact |
| North = shared bearer, registry = allowlist | Goal 3, FR-3/4/5 | Exact |
| South = per-host token in URL, clean stored remote | Goal 4, FR-6 | Exact |
| `token_user` field name | Tech Considerations + FR-6 | Exact |
| YAML config | Tech Considerations, FR-3 | Exact |

Brainstorm open questions (CA bundling, network reachability, bind surface) and
all seven scope cuts are carried into PRD Open Questions + Non-Goals. No drift.

## 2 & 3. Intent → Task-Coverage Matrix

| ID | Requirement (abbrev.) | Owning task(s) | Covered? | Notes |
|----|-----------------------|----------------|----------|-------|
| US-001 | Vertical slice | TASK-4 | Full | 1:1; all story ACs land in TASK-4 |
| US-002 | Registry, routing, allowlist | TASK-5 | Full | adds explicit defaults-merge AC |
| US-003 | TTL cache + `/refresh` | TASK-6 | Full | injectable clock + concurrency spy |
| US-004 | North bearer + south creds | TASK-7 | Full | both surfaces, one choke point |
| US-005 | Docker + compose + README | TASK-8 | Full | offline `compose config` gate separated from manual build/up |
| FR-1 | `/{owner}/mcp` reusing core | TASK-4 #3,#5 | Full | generalized in TASK-5 #3 |
| FR-2 | Shallow-clone, no mounts | TASK-4 #3,#6 | Full | `file://` fixture proves no working-tree path |
| FR-3 | Single `servers.yaml`; owners=allowlist | TASK-5 #1,#4 | Full | |
| FR-4 | Unregistered owner → 404 | TASK-5 #4 | Full | |
| FR-5 | Bearer/401; `/healthz` open | TASK-7 #1,#2 | Full | |
| FR-6 | Per-host token URL; clean remote | TASK-7 #3,#5,#6 | Full | `.git/config` inspection |
| FR-7 | Committed content + TTL (60s default) | TASK-6 #1,#2 | Full, gap G1 | 60s default un-pinned in ACs |
| FR-8 | `/refresh` force + JSON summary | TASK-6 #3 | Full | keys enumerated |
| FR-9 | Per-owner lock; owners independent | TASK-6 #4 | Full | |
| FR-10 | Eager background clone; `/healthz` immediate | TASK-5 #5 | Full | |
| FR-11 | Dockerfile+compose + idempotent `up -d` | TASK-8 #1,#2,#3 | Full, gap G2 | idempotency not gated |
| FR-12 | stdio + 82 tests unchanged | TASK-4 #2,#7; #7 in 5/6/7; #6 in 8 | Full | every task asserts it |

Every FR and US has exactly one clear owning task; nothing orphaned. Dependency
DAG acyclic and correctly staged: TASK-4 → TASK-5 → {TASK-6, TASK-7} → TASK-8.

## Non-Goal / Scope-Cut Violations — None detected

Audited every AC for leakage of PRD non-goals and brainstorm scope cuts
(live-tree serving, per-owner containers, third-party proxy, launchd/systemd,
per-token scoping, IP allowlist, webhook wiring, CA bundling, live-Bitbucket
tests). All correctly absent or actively excluded.

## Cross-task contract consistency

- **(a) servers.yaml schema — CONSISTENT.** TASK-5 is the sole authoritative
  definer; TASK-7 restates only the `credentials` slice it consumes, matching
  exactly; TASK-8 sample agrees field-for-field.
- **(b) Two auth surfaces — CONSISTENT.** North/south stated identically across
  TASK-7 ACs, FR-5/6, brainstorm; env var names consistent between TASK-7 and
  TASK-8.
- **(c) Routing / 404 / open /healthz — CONSISTENT.** `/{owner}/mcp` identical in
  TASK-4/5; `/healthz` 200-when-up (TASK-4 #4) and open (TASK-7 #2) are
  complementary; 404 owned by TASK-5 #4.

## AC quality / gaps (all minor — none block the build)

**Strengths:** every AC offline+verifiable (`file://` fixtures, TestClient,
`docker compose config`, `.git/config` inspection, injectable TTL clock); the
"82 stdio tests untouched" constraint asserted in all five tasks, with TASK-4 #2
uniquely asserting no edits to the stdio files; JSON `/refresh` keys enumerated;
concurrency AC testable.

- **G1 (minor):** TTL default `60s` (FR-7) not asserted in any AC — pin in
  TASK-5 #2 or TASK-6.
- **G2 (minor):** `docker compose up -d` idempotency claimed only in README text,
  not gated (correctly a manual check) — label as such in TASK-8.
- **G3 (minor):** the shared `file://` bare-repo conftest fixture is required by
  TASK-4/5/6/7 but not explicitly owned by any AC — assign creation to TASK-4.
- **G4 (very minor):** the `load_docs(config: ServerConfig)` reuse seam not
  spelled out; add an implementation note to TASK-4 so the implementer builds
  `ServerConfig(owner=<name>, roots=(<checkout>,))` rather than changing
  `load_docs`'s signature (would breach FR-12).
- **G5 (very minor):** no AC asserts the four new deps (`pyyaml`, `starlette`,
  `uvicorn`, `pydantic`) are added via `uv add` per the uv-only project rule.
- **Note (not a gap):** TASK-5 #5 will need to retrofit TASK-4's startup from
  clone-then-serve to serve-then-lazy-resolve; expected, not called out in an AC.

## Success Metric Assessment

| Metric | Status | Notes |
|--------|--------|-------|
| Devcontainer reads owner over HTTP+bearer, no mount | Hypothesis | offline analog gated (TASK-4 #5/#6 + TASK-7 #1); end-to-end is manual |
| Adding an owner = one-line edit | Measurable | TASK-5 #3 + #2 |
| Bitbucket→GitHub = data-only url change | Measurable | TASK-7 #6 tests the provider-neutral seam |
| `up -d` no-op when running | Hypothesis | see G2 — documented manual check |
| Zero regressions: 82 stdio tests | Measurable | asserted in all five tasks |

No metric unmeasurable or contradicted.

## Reviewer Notes

Planning set is unusually clean: brainstorm→PRD lossless, PRD→tasks near-perfect
1:1, DAG acyclic and correctly staged. G1–G5 are AC-hardening opportunities, not
coverage holes — recommend folding G1 (pin 60s) and G3 (own the shared `file://`
fixture in TASK-4) before starting, as those most affect downstream tasks.
Implementation heads-up for TASK-4: reuse seam is `ServerConfig`, not a path.

**Verdict: Aligned** — planning is internally coherent, complete, and ready to build.
