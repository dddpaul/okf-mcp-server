---
id: TASK-17
title: >-
  Gateway offline volume-cache fallback (serve last-good checkout when git
  source is unavailable)
status: Done
assignee: []
created_date: '2026-08-04 20:49'
updated_date: '2026-08-04 21:21'
labels:
  - 'feature:http-gateway'
dependencies: []
priority: medium
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Direction:** Make the persisted Docker volume checkout an authoritative offline fallback — a git-source outage degrades to *stale-but-served*, never *empty-and-failed* — uniformly across startup and refresh (chosen: Option B scope + Option A synchronous refresh-then-fallback).

**Locked decisions (with rationale):**
- **Scope = startup + refresh:** one rule everywhere — source-unavailable ⇒ serve last-good. *Rationale:* the outage principle is identical at boot and at TTL refresh; unifying is less code than special-casing startup.
- **Synchronous refresh-then-fallback:** load() tries fetch_and_reset on an existing checkout and serves it as-is on git failure; only absent/corrupt goes to a fresh clone. *Rationale:* reuses fetch_and_reset/_pull_blocking verbatim and keeps the existing synchronous ready-gate — no background-task machinery.
- **Never rmtree a good checkout:** the destructive rmtree only runs for absent/corrupt checkouts. *Rationale:* the current unconditional rmtree is the root cause of the data loss.
- **Integrity gate = git rev-parse HEAD:** corrupt checkout is discarded and re-cloned. *Rationale:* cheap, decisive signal already used by head_commit; corrupt content has no fallback value.
- **CredentialError + good checkout ⇒ serve stale:** missing south token behaves like a source outage when servable content exists; empty volume still fails. *Rationale:* can't-authenticate ≡ can't-reach; empty-volume path still catches real misconfig loudly, and /status makes it non-silent.
- **get_or_refresh serves stale, /refresh returns 502:** per-request TTL refresh never raises (self-heals on next success); explicit POST /refresh returns 502 on source-down but keeps serving. *Rationale:* implicit refresh must not break MCP requests; explicit refresh must report loudly for scripts.
- **Stale owner = serving, not failed:** source_available:false marks the fallback; content path is unchanged. *Rationale:* the owner genuinely answers requests; failed is reserved for "nothing to serve".

**Scope cuts:**
- No async serve-then-refresh / background refresh task.
- No forced "offline mode" config flag / air-gap toggle — fallback is automatic on failure, never operator-forced.
- No change to the stdio path (server.py run()/serve_stdio/cli.py) or its 82 tests — this is entirely gateway-side.
- No new persistence format or volume-layout change — the existing named volume and per-owner checkout dirs are reused as-is.

**Implementation checklist:**
- Add source_available/last_pull_attempt_at/last_pull_error fields + _valid_checkout_exists + _serve_existing to OwnerCache; grow _apply to stamp them.
- Rewrite load() to the branch table (valid->refresh-or-fallback; absent/corrupt->rmtree-if-present + clone).
- Make get_or_refresh non-raising on pull failure (serve existing, stamp fields).
- Make force_refresh signal source-down to the route (typed exception) for the 502 mapping; keep serving.
- Add the four fields to _owner_status; keep stale owners as serving.
- Map source-down to 502 in the /refresh route.
- Update README.md; add the offline tests to tests/test_gateway_*.py.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Restart with a healthy checkout and an unreachable file:// source: owner is serving, source_available=false, stale=true, served_commit equals the pre-outage SHA
- [x] #2 Restart with a corrupt checkout (rm -rf <dest>/.git) and source-down: owner is failed; with source-up it re-clones clean and serves
- [x] #3 Empty volume and source-down: owner is failed (nothing to serve)
- [x] #4 Unset south token with a healthy checkout: owner is serving+stale; unset token with an empty volume: owner is failed
- [x] #5 Outage then restore source: next get_or_refresh flips source_available=true and advances served_commit (self-heal)
- [x] #6 POST /{owner}/refresh with source-down returns HTTP 502, body carries source_available:false + scrubbed error + still-served served_commit; MCP content requests for that owner still succeed
- [x] #7 /status exposes source_available, stale, last_pull_attempt_at, last_pull_error per owner; scrubbed error never contains a token
- [x] #8 A good checkout is never rmtree'd on startup (only absent/corrupt checkouts are discarded)
- [x] #9 The 82 stdio tests remain untouched and green; uv run mypy . && uv run ruff check . and uv run pytest all pass
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: Implement offline volume-cache fallback per design addendum. (1) owner_cache.py: add fields source_available/last_pull_attempt_at/last_pull_error to __init__; add _valid_checkout_exists (git rev-parse HEAD gate), _serve_existing (scan+build from on-disk HEAD, no source contact), _stamp_attempt (record attempt without content swap); grow _apply to (*, source_available, last_pull_error) — always stamps attempt fields, stamps success clocks (last_pulled) only when source_available; rewrite load() to branch table (valid->pull-or-serve-existing; absent/corrupt->clone, stamp+raise on source-error); make get_or_refresh serve-stale on (CalledProcessError,CredentialError) without raising; make force_refresh raise typed RefreshUnavailable(served_commit,error) on source-down after stamping. (2) app.py: add source_available/stale/last_pull_attempt_at/last_pull_error to _owner_status entries (stale = source_available is False and commit not None; scrub last_pull_error at render); map RefreshUnavailable -> 502 in /refresh route. (3) README: offline-fallback bullet + /status fields + /refresh 502 contract. (4) tests/test_gateway_offline.py: AC#1-8 (rename-bare source outage + manual-checkout CredentialError patterns); update the exact key-set assertion in test_gateway_status.py. Full mypy/ruff/pytest must pass (AC#9).

Commit: `dac3420` - task-17: offline volume-cache fallback — serve last-good checkout on git-source outage

Commit: `4ca2a82` - task-17: add direct get_or_refresh-stale and 502 token-scrub tests; wrap long lines

Implemented offline volume-cache fallback across startup + refresh. owner_cache.py: added source_available/last_pull_attempt_at/last_pull_error fields; _valid_checkout_exists (git rev-parse HEAD integrity gate), _serve_existing (scan+build from on-disk HEAD, no source contact), _stamp_attempt (record attempt without content swap or success-clock), RefreshUnavailable typed exception; _apply grew (*, source_available, last_pull_error) and stamps last_pulled ONLY when source_available=True (so a stale serve stays past-TTL and self-heals on the next successful pull). load() = branch table: healthy checkout -> _pull_blocking, fall back to _serve_existing on (CalledProcessError|CredentialError); absent/corrupt -> _clone_blocking (clone_owner rmtree's only these), stamp+raise on source-error. clone_owner (the sole rmtree caller) is unreachable from the healthy branch => a good checkout is never destroyed. get_or_refresh serves stale (no raise) on source-down; force_refresh raises RefreshUnavailable(served_commit,error). app.py: _owner_status adds the 4 fields (stale = source_available is False and commit is not None; last_pull_error scrubbed at render); /refresh maps RefreshUnavailable -> 502 {owner,served_commit,source_available:false,error}. README: offline-fallback bullet + /status fields + /refresh 502 contract. Tests: tests/test_gateway_offline.py (12 tests, all 9 ACs incl. direct get_or_refresh-stale + 502 token-scrub) + updated the exact key-set lock in test_gateway_status.py. Gate: uv run mypy . (29 files clean), ruff clean, pytest 178 passed/1 skipped. Stdio path + its tests untouched (AC#9). REVIEW: mandated task-reviewer agent is UNREGISTERED this session (no .claude/agents, not in available agent types); substituted an independent claude agent with the reviewer charter on git diff master..HEAD -> VERDICT APPROVED (all 9 ACs met with real tests, rmtree-safety/self-heal/token-scrub verified). Its 2 coverage-gap notes were then closed with the 2 added tests; its line-length note fixed (all changed lines <=88); its 'AC#9 says 82 stdio tests' label nit is in the AC text, non-actionable (actual: server.py=36, total non-gateway=133, all green, diff touches zero stdio files).
<!-- SECTION:NOTES:END -->
