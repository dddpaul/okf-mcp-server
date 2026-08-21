---
id: doc-2
title: Owner Freshness Semantics
type: other
created_date: '2026-08-21 06:49'
---

Normative definition of the per-owner `freshness` enum that
`GET /status` emits for every owner of the okf-mcp-server HTTP gateway.

This is the contract a mesh consumer (control-gateway and anything downstream of
it) reads. The producer computes the verdict; **no consumer may re-derive it**
from the primitives. That rule exists because a verdict with no authoritative
owner is exactly what produced the observed bug this doc closes: a consumer
reported `freshness: null` beside a `served_commit` that had visibly moved.

## 1. The four states

`freshness` is a string, always present on every owner entry of `GET /status`
(with and without `?artifacts=true`), and always one of exactly four values. It
is never `null` and never absent — an owner that has loaded nothing still reports
`unknown` rather than omitting the field.

| state | meaning | is the owner answering MCP requests? |
| --- | --- | --- |
| `fresh` | Serving the content of the last successful pull, and that pull is within the owner's TTL. | yes |
| `stale_ttl` | The source is reachable, but the last successful pull is older than the TTL, so a refresh is due on the next content request. | yes |
| `stale` | The last git attempt failed; the owner is serving its last-good checkout as an offline fallback. | yes |
| `unknown` | Nothing has ever loaded for this owner — the startup clone is still in flight, or it failed with no checkout to fall back on. | not yet (`loading`), or no (`failed`) |

Three of the four states describe an owner that **is** serving content. Only
`unknown` may mean there is nothing to serve; `stale` in particular is a
degraded-but-working state, not an outage.

## 2. Precedence

The verdict is computed by first match, in this order:

```
commit is None                     -> unknown     (never loaded: loading or failed-empty)
elif source_available is False     -> stale       (offline fallback; last-good path)
elif last_pulled_age_seconds > ttl -> stale_ttl   (source reachable, refresh due next request)
else                               -> fresh       (served the last successful pull, within TTL)
```

The order is load-bearing, and each step exists for a reason:

- **No commit outranks source-down.** An owner whose first clone failed has both
  `source_available: false` and no content. It reports `unknown`, not `stale`,
  because `stale` promises last-good content is being served and there is none.
- **Source-down outranks past-TTL.** A failed pull leaves the *success* clock
  frozen, so an offline owner is usually past its TTL as well. It reports
  `stale`, not `stale_ttl`, because "a refresh is due" says nothing useful while
  the source is unreachable — and because a `stale_ttl` owner self-clears on the
  next request, while a `stale` one cannot until the source returns.
- **The TTL comparison is strictly greater-than.** An age exactly equal to the
  TTL is still `fresh`; `stale_ttl` starts one second past it.
- **An unknown age falls through to `fresh`.** If a commit is on hand and the
  source is reachable but no successful pull has stamped an age
  (`last_pulled_age_seconds: null`), there is no age to call past-TTL, so the
  verdict is `fresh`.

### Relationship to the existing `stale` boolean

The pre-existing `stale` boolean is retained unchanged for back-compat, and the
two agree by construction:

```
freshness == "stale"   if and only if   stale == true
```

A consumer written against `stale` and one written against `freshness` can never
disagree. Note the asymmetry this implies and the precedence guarantees: an
owner with `stale: false` may still be `stale_ttl` or `unknown` — **`stale:
false` does not mean `fresh`.** Only `freshness == "fresh"` means fresh.

## 3. Transitions

| from | to | trigger |
| --- | --- | --- |
| `unknown` | `fresh` | The first successful clone/pull lands: `commit`, the success clock, and `source_available: true` are all set together. |
| `unknown` | `stale` | Startup finds a healthy checkout in the persisted volume but cannot reach the source, so it serves that checkout as last-good. |
| `fresh` | `stale_ttl` | **No state is written.** The monotonic clock simply crosses the TTL. |
| `stale_ttl` | `fresh` | Any successful pull — the TTL refresh on the next `/{owner}/mcp` request, or an explicit `POST /{owner}/refresh` — re-stamps the success clock. |
| `fresh` / `stale_ttl` | `stale` | A pull attempt fails (source unreachable, ref gone, or south credential unset). The served commit is retained; the success clock is left frozen. |
| `stale` | `fresh` | A later pull attempt succeeds. `source_available` flips back and the success clock is re-stamped. |
| `unknown` | `unknown` | A first clone that fails with no checkout to fall back on: the owner enters `failed` and stays `unknown`. |

`fresh -> stale_ttl` is the only transition with no corresponding event. It is a
pure function of elapsed time, which is why a passive read can observe it at all:
`GET /status` never pulls, so it reports `stale_ttl` honestly instead of hiding
it behind an implicit refresh. A real content request through `/{owner}/mcp` does
pull, so `stale_ttl` typically clears on the next actual use.

There is no transition **out of** `stale` on a clock tick, and none out of
`unknown` on anything but a successful load. Both require the source to come
back.

## 4. Serving-freshness, not source-freshness

This is the caveat that most affects a consumer's decisions.

`fresh` means: **"what I serve is current as of my last successful contact with
the source, and that contact was within my TTL."**

`fresh` does **not** mean: "the source has not advanced since." The gateway makes
**no network probe on `GET /status`** — no `git ls-remote`, no source-ahead
check. `/status` is a pure, network-free, offline-safe read of local state. An
owner can therefore be `fresh` while its upstream repository has commits the
gateway has not pulled yet.

Consequences for a consumer:

- **Do not read `fresh` as "up to date with the source."** Read it as "recently
  synced, and the sync worked."
- To confirm a specific upstream change actually landed, use `served_commit`
  (the provenance signal) — e.g. check that a known merge commit is an ancestor
  of it — rather than inferring it from `freshness`.
- To detect whether a *specific artifact* changed, use its per-doc
  `content_hash` from `GET /status?artifacts=true`, not `freshness`.
- To force a sync rather than observe one, call `POST /{owner}/refresh`, which
  answers `502` if the source is unreachable.

Freshness is deliberately **per-owner, never per-doc**: every doc an owner serves
comes from one checkout that moves as a unit, so a per-doc freshness value would
be identical for all of them. The per-doc signal is `content_hash`.

## 5. Producer / consumer boundary

**okf-mcp-server owns exactly these four states and nothing more.** It emits
`fresh`, `stale_ttl`, `stale`, `unknown` — the vocabulary of one gateway serving
one owner's checkout.

**Mesh-level concepts are derived by control-gateway and are never emitted by
okf.** In particular `blocked_upstream` is a control-gateway conclusion derived
from `unknown` / `stale`: both mean the gateway cannot presently confirm it has
current content for that owner, which is what makes a dependent goal blocked.
`stale_ttl` is *not* a blocked signal on its own — the source is reachable and
the next content request refreshes it.

The rule in both directions:

- The producer surfaces truth. It never guesses at what a consumer will conclude
  and never emits mesh vocabulary.
- The consumer passes truth through and derives its own conclusions **on top of**
  the verdict. It never re-derives the verdict itself from `source_available`,
  `last_pulled_age_seconds`, and `ttl`. Those primitives remain on `/status` for
  debugging and display; the field that decides is `freshness`.

## 6. Where this is implemented

- `_freshness()` in `src/okf_mcp_server/gateway/app.py` — the precedence, as a
  pure function.
- `_owner_status()` in the same module — calls it once per owner, over the same
  state snapshot the neighbouring primitives are rendered from, so the verdict
  can never contradict the fields printed beside it.
- `tests/test_gateway_status.py` — drives all four states, the strict TTL
  boundary, the source-down-outranks-past-TTL precedence, and the
  `freshness == "stale"` ⟺ `stale == true` invariant.
- `README.md`, *Inspect live per-owner status* — the operator-facing summary.
