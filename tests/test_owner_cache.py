"""US-003: per-owner pull-on-demand TTL cache unit tests.

Every test is offline — ``file://`` bare-repo fixtures are the clone sources and
a ``FakeClock`` drives TTL staleness deterministically (no sleeping on wall
time). Covers: within-TTL requests do not re-pull, past-TTL requests reflect a
pushed change, an unchanged tree reuses the built server, concurrent stale
requests collapse to a single pull, and one owner's in-flight pull never blocks
another owner.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import FakeClock, GitRepoFixture, push_commit

from okf_mcp_server.gateway import owner_cache as owner_cache_module
from okf_mcp_server.gateway.owner_cache import OwnerCache, RefreshResult
from okf_mcp_server.gateway.registry import ResolvedOwner

REFERENCE_DOC = """---
export: true
type: Reference Doc
id: gw-ref-1
title: Gateway Reference
description: Reference served over the gateway.
---
# Gateway Reference

Body of the gateway reference doc.
"""

DECISION_DOC = """---
export: true
type: Architecture Decision
id: gw-adr-1
title: Gateway ADR
---
# Gateway ADR

The gateway decision body.
"""

CHANGED_REFERENCE_DOC = """---
export: true
type: Reference Doc
id: gw-ref-1
title: Gateway Reference
description: Reference served over the gateway.
---
# Gateway Reference

UPDATED gateway reference body.
"""

FIXTURE_FILES = {
    "docs/reference.md": REFERENCE_DOC,
    "design/adr.md": DECISION_DOC,
    "README.md": "# readme\n\nNo frontmatter, not served.\n",
}


def _cache_for(
    source: GitRepoFixture,
    dest: Path,
    clock: Callable[[], float],
    *,
    owner: str = "acme",
    ttl: int = 60,
) -> OwnerCache:
    resolved = ResolvedOwner(owner=owner, url=source.url, ref=source.ref, ttl=ttl)
    return OwnerCache(resolved, dest, clock=clock)


def _reference_body(cache: OwnerCache) -> str:
    for doc in cache.docs:
        if doc.id == "gw-ref-1":
            return doc.content
    raise AssertionError("reference doc gw-ref-1 not loaded")


def test_within_ttl_no_repull_after_ttl_reflects_change(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    clock = FakeClock()
    cache = _cache_for(source, tmp_path / "acme", clock, ttl=60)

    async def scenario() -> tuple[str, str, str]:
        await cache.load()  # last_pulled = clock() = 0
        before = _reference_body(cache)
        # Mutate the source only after the gateway already cloned it.
        push_commit(source, {"docs/reference.md": CHANGED_REFERENCE_DOC})
        clock.advance(30)  # still within ttl=60 -> no re-pull
        await cache.get_or_refresh(60)
        within = _reference_body(cache)
        clock.advance(40)  # now 70s old -> stale -> re-pull
        await cache.get_or_refresh(60)
        after = _reference_body(cache)
        return before, within, after

    before, within, after = asyncio.run(scenario())

    assert "Body of the gateway reference doc." in before
    assert within == before  # within TTL: served content is unchanged (no pull)
    assert "UPDATED gateway reference body." in after  # after TTL: reflects change


def test_stale_pull_without_source_change_reuses_server(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    clock = FakeClock()
    cache = _cache_for(source, tmp_path / "acme", clock, ttl=60)

    async def scenario() -> tuple[object, object, str | None, str | None]:
        await cache.load()
        first_server = cache.server
        first_commit = cache.commit
        clock.advance(100)  # stale, but the source never moved
        await cache.get_or_refresh(60)
        return first_server, cache.server, first_commit, cache.commit

    first_server, second_server, first_commit, second_commit = asyncio.run(scenario())

    # HEAD did not move, so load_docs/build_server are skipped and the server is reused.
    assert second_server is first_server
    assert second_commit == first_commit


def test_stale_pull_with_source_change_rebuilds_server(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    clock = FakeClock()
    cache = _cache_for(source, tmp_path / "acme", clock, ttl=60)

    async def scenario() -> tuple[object, object, str, str | None]:
        await cache.load()
        first_server = cache.server
        new_head = push_commit(source, {"docs/reference.md": CHANGED_REFERENCE_DOC})
        clock.advance(100)  # stale
        await cache.get_or_refresh(60)
        return first_server, cache.server, new_head, cache.commit

    first_server, second_server, new_head, commit = asyncio.run(scenario())

    # HEAD moved, so the owner's Server is rebuilt on the fresh docs.
    assert second_server is not first_server
    assert commit == new_head


def test_force_refresh_ignores_ttl_and_summarizes(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    clock = FakeClock()
    cache = _cache_for(source, tmp_path / "acme", clock, owner="acme", ttl=60)

    async def scenario() -> tuple[RefreshResult, str]:
        await cache.load()
        new_head = push_commit(
            source, {"docs/reference.md": CHANGED_REFERENCE_DOC}, message="edit"
        )
        # No clock advance: the owner is well within TTL, yet force must still pull.
        result = await cache.force_refresh()
        return result, new_head

    result, new_head = asyncio.run(scenario())

    assert result.owner == "acme"
    assert result.ref == "main"
    assert result.commit == new_head  # forced pull advanced HEAD despite fresh TTL
    assert result.docs_loaded == 2  # reference + adr (README is not exported)


def test_concurrent_stale_requests_pull_once(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    clock = FakeClock()
    cache = _cache_for(source, tmp_path / "acme", clock, ttl=60)

    fetch_calls: list[str] = []
    real_fetch = owner_cache_module.fetch_and_reset

    def spy_fetch(checkout: Path, ref: str) -> None:
        fetch_calls.append(ref)
        # Widen the overlap window so the second request is parked on the lock
        # (runs in the worker thread, so the event loop stays free).
        time.sleep(0.05)
        real_fetch(checkout, ref)

    monkeypatch.setattr(owner_cache_module, "fetch_and_reset", spy_fetch)

    async def scenario() -> tuple[object, object]:
        await cache.load()  # initial clone (not counted; uses clone_owner)
        push_commit(source, {"docs/reference.md": CHANGED_REFERENCE_DOC})
        clock.advance(100)  # both requests see a stale owner
        return await asyncio.gather(
            cache.get_or_refresh(60), cache.get_or_refresh(60)
        )

    server_a, server_b = asyncio.run(scenario())

    assert len(fetch_calls) == 1  # per-owner lock collapsed the double-pull to one
    assert server_a is server_b  # both requests observe the same rebuilt server


def test_pull_on_one_owner_does_not_block_another(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow_src = make_bare_repo(FIXTURE_FILES, ref="main")
    fast_src = make_bare_repo(FIXTURE_FILES, ref="main")
    clock = FakeClock()
    slow = _cache_for(slow_src, tmp_path / "slow", clock, owner="slow", ttl=60)
    fast = _cache_for(fast_src, tmp_path / "fast", clock, owner="fast", ttl=60)

    gate = threading.Event()
    real_fetch = owner_cache_module.fetch_and_reset

    def gated_fetch(checkout: Path, ref: str) -> None:
        # Block only the slow owner's fetch (in its worker thread) until released.
        if checkout == slow.checkout:
            assert gate.wait(timeout=30)
        real_fetch(checkout, ref)

    monkeypatch.setattr(owner_cache_module, "fetch_and_reset", gated_fetch)

    async def scenario() -> tuple[object, bool]:
        await asyncio.gather(slow.load(), fast.load())
        push_commit(fast_src, {"docs/reference.md": CHANGED_REFERENCE_DOC})
        clock.advance(100)  # both stale
        slow_task = asyncio.create_task(slow.get_or_refresh(60))  # parks in the gate
        try:
            # The fast owner must refresh to completion while slow is still stuck.
            fast_server = await asyncio.wait_for(fast.get_or_refresh(60), timeout=10)
            slow_still_blocked = not slow_task.done()
        finally:
            gate.set()  # release the slow owner for a clean shutdown
            await slow_task
        return fast_server, slow_still_blocked

    fast_server, slow_still_blocked = asyncio.run(scenario())

    assert fast_server is not None
    assert slow_still_blocked  # fast finished with the slow owner's pull mid-flight
