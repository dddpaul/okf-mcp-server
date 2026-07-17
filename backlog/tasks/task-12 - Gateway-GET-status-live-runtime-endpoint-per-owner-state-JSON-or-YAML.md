---
id: TASK-12
title: 'Gateway GET /status live-runtime endpoint (per-owner state, JSON or YAML)'
status: Done
assignee: []
created_date: '2026-07-17 12:21'
updated_date: '2026-07-17 12:43'
labels:
  - 'feature:http-gateway'
dependencies: []
priority: medium
ordinal: 12000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
**Direction:** Option A — add a global, bearer-gated, read-only GET /status endpoint (JSON default, ?format=yaml), rendering live per-owner runtime state with render-time credential scrubbing; minimal and additive, mirroring /config.

**Locked decisions (with rationale):**
- **Global GET /status, one call lists all owners.** *Rationale:* the audience is ops wanting an at-a-glance view of every owner at once.
- **Human/ops audience — always 200, rich detail, behind the north bearer token (not /healthz-open).** *Rationale:* it's a debugging view, not a machine health probe; the middleware already gates every route but /healthz.
- **Pure read — never triggers a pull or any side effect.** *Rationale:* status observes current state; refreshing is /{owner}/refresh's job.
- **State enum derived from existing OwnerState** (loading/serving/failed). *Rationale:* no new flags; ready/session_manager/error already encode it — ready unset => loading; ready set + session_manager present => serving; ready set + session_manager is None => failed (error populated).
- **Two clocks in OwnerCache: monotonic for TTL, new injectable wall clock for display.** *Rationale:* TTL must stay monotonic (jump-immune); humans need an absolute timestamp; both injectable keeps tests deterministic.
- **Report both last_pulled_at (ISO 8601 UTC) and last_pulled_age_seconds.** *Rationale:* timestamp for humans, age for quick 'is it stale' scanning. age = int(cache._clock() - cache.last_pulled); last_pulled_at from the new wall stamp.
- **Render-time credential scrub (Option A), applied only to the failed-owner error message.** *Rationale:* a clone-failure exception can embed the south git token in the URL; scrubbing at render keeps the change minimal and off the already-reviewed git_source.
- **Include a top-level summary counts block.** *Rationale:* at-a-glance totals are the point of a global status view.
- **Match /config format handling** (?format= query param, YAML via application/yaml, unsupported value => 400). *Rationale:* one consistent surface across the two introspection endpoints.

**Scope cuts:**
- No per-owner GET /{owner}/status route (global only).
- No machine-monitoring semantics — status is always 200, never reflects health in the HTTP status code; /healthz remains the liveness probe.
- Do NOT echo owner url in the status body.
- No source-level (git_source) scrubbing — render-time only (Option A, not B/C).
- No change to TTL/refresh behavior; owner_cache.py edits are additive only.

**Response shape** (default JSON; ?format=yaml identical to /config; error key present only for state=failed; commit/docs_loaded/last_pulled_* are null/0 while loading):

```json
{
  "summary": { "total": 3, "serving": 2, "loading": 0, "failed": 1 },
  "owners": {
    "acme": {
      "state": "serving", "ref": "main", "commit": "1a2b3c4d…",
      "docs_loaded": 42, "last_pulled_at": "2026-07-17T07:46:46Z",
      "last_pulled_age_seconds": 340
    },
    "beta": {
      "state": "failed", "ref": "release", "commit": null,
      "docs_loaded": 0, "last_pulled_at": null, "last_pulled_age_seconds": null,
      "error": { "type": "CloneError", "message": "fatal: repository not found (bitbucket.corp)" }
    }
  }
}
```

**Credential scrub helper** (app.py, pure; applied only to failed-owner error.message; type(err).__name__ passes through raw):

```python
import re
_CRED_IN_URL = re.compile(r"(?P<scheme>https?://)[^/@\s]+@")
def _scrub_credentials(text: str) -> str:
    return _CRED_IN_URL.sub(r"\g<scheme>***@", text)
```

**Acceptance criteria (sketch):** see the checked ACs below.

**Implementation checklist:**
- owner_cache.py: add injectable wall_clock (default time.time), add last_pulled_wall: float | None field, stamp it in _apply alongside the existing last_pulled (three additive spots, no behavior change).
- app.py: add _owner_status(owners) helper (sibling of _effective_config) building the summary + owners maps; add _scrub_credentials(text) helper; add an async status route reusing the /config ?format= + 400 handling; register Route('/status', status, methods=['GET']) right after /config.
- README.md: document GET /status, the state enum, the fields, and ?format=, next to the /config docs.
- tests/test_gateway_status.py: TestClient + file:// bare-repo fixtures per the cases in the ACs.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 GET /status returns 200 with a JSON body by default whose top-level keys are summary and owners; each owner entry shows state, ref, commit, docs_loaded, last_pulled_at, and last_pulled_age_seconds
- [x] #2 The summary block reports total/serving/loading/failed counts matching the owners map
- [x] #3 A serving owner shows state=serving, non-null commit, docs_loaded matching its fixture, an ISO 8601 last_pulled_at, and an integer last_pulled_age_seconds; with a fixed injected wall clock the ISO string is exact and advancing the injected monotonic clock by N yields last_pulled_age_seconds == N
- [x] #4 A failed owner shows state=failed, an error object with type and a scrubbed message, and null commit/last_pulled_at/last_pulled_age_seconds, and is counted in summary.failed
- [x] #5 When an owner's clone fails with a token-bearing URL in the exception, the token string appears nowhere in the /status response body (JSON and YAML)
- [x] #6 A still-cloning owner shows state=loading and GET /status returns without blocking on its readiness
- [x] #7 GET /status?format=yaml returns 200 with application/yaml that yaml.safe_load round-trips to the same structure as the JSON body; an unsupported ?format= value (e.g. xml) returns 400
- [x] #8 When auth is configured, /status requires the bearer token (missing/wrong returns 401, correct returns 200); GET /healthz stays open
- [x] #9 owner_cache.py changes are additive (injectable wall_clock + last_pulled_wall field + one _apply stamp); the monotonic TTL clock is unchanged and US-003 TTL tests stay green
- [x] #10 The existing 82 stdio tests remain green and their test files are unchanged; lint (uv run mypy . && uv run ruff check .) and tests (uv run pytest) pass
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Plan: mirror /config. (1) owner_cache.py additive: inject wall_clock=time.time, add last_pulled_wall field, stamp it in _apply. (2) app.py: _scrub_credentials + _iso_utc + _owner_status(owners) helpers; async status route reusing /config ?format=+400 handling; Route('/status') after /config; thread wall_clock through create_app+OwnerCache. (3) README /status section next to /config. (4) tests/test_gateway_status.py: serving/failed/loading/scrub/yaml/auth cases via file:// bare-repo fixtures + injected clocks.

Commit: `275334e` - task-12: add gateway GET /status live-runtime endpoint (per-owner state, JSON/YAML)

Implemented: additive GET /status endpoint mirroring /config. app.py gains _scrub_credentials (render-time URL-userinfo redaction), _iso_utc (ISO 8601 UTC, whole seconds), and _owner_status(owners) building the summary + per-owner state map; the async status route reuses /config's ?format=+400 handling and is registered right after /config (behind the same north token). owner_cache.py is strictly additive: injectable wall_clock=time.time, last_pulled_wall field, one _apply stamp; the monotonic TTL clock/last_pulled/_is_fresh are untouched. State enum derived from existing OwnerState (loading/serving/failed); last_pulled_at from the wall stamp, last_pulled_age_seconds=int(cache._clock()-last_pulled). Docs: README /status section + design addendum. Tests: tests/test_gateway_status.py (7 cases) covering shape/summary, serving fields with injected clocks, failed+scrub, token-never-in-body (JSON+YAML), loading non-blocking, yaml round-trip + 400, and the bearer gate. Gate: mypy clean, ruff clean, pytest 161 passed/1 skipped (skip pre-existing). Review: APPROVED (task-reviewer 8-item checklist run in an independent fresh-context subagent because the plugin-provided task-reviewer type is not registered in this runtime).
<!-- SECTION:NOTES:END -->
