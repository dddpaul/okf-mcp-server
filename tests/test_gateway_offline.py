"""TASK-17: offline volume-cache fallback (serve last-good on a source outage).

Every test is offline and network-free. A git-source *outage* is simulated by
removing or renaming a ``file://`` bare repo (a real ``git fetch``/``clone``
against it then fails with a ``CalledProcessError``); a missing *south
credential* is simulated with an authenticated host whose ``token_env`` is unset
(``build_authenticated_url`` raises ``CredentialError`` before any git runs, so
no network is touched). A "restart" is two ``create_app``/``OwnerCache``
instances sharing one cache directory — the persisted checkout stands in for the
named Docker volume that survives a container restart.

Covers the branch table: a healthy checkout degrades to stale-but-served on a
source outage (startup and refresh alike); an absent or corrupt checkout with the
source down fails; a good checkout is never discarded; an outage self-heals on
the next successful pull; ``POST /{owner}/refresh`` reports 502 while still
serving; and ``GET /status`` exposes the offline fields with a scrubbed error.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
from conftest import FakeClock, GitRepoFixture, push_commit
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

import pytest

from okf_mcp_server.gateway import Registry, create_app
from okf_mcp_server.gateway import owner_cache as owner_cache_module
from okf_mcp_server.gateway.git_source import clone_owner, head_commit
from okf_mcp_server.gateway.owner_cache import OwnerCache
from okf_mcp_server.gateway.registry import Credential, OwnerSpec, ResolvedOwner

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

# Two exported docs (+ one un-exported readme) => docs_loaded == 2 when serving.
FIXTURE_FILES = {
    "docs/reference.md": REFERENCE_DOC,
    "design/adr.md": DECISION_DOC,
    "README.md": "# readme\n\nNo frontmatter, so it is never served.\n",
}

EXPECTED_URIS = {
    "knowledge://acme/reference-doc/gw-ref-1",
    "knowledge://acme/architecture-decision/gw-adr-1",
}

# A token that MUST never survive into a rendered /status error message.
GIT_TOKEN_SECRET = "sekret-token-value-9999"


def _registry(source: GitRepoFixture, owner: str = "acme") -> Registry:
    return Registry(owners={owner: OwnerSpec(url=source.url, ref=source.ref)})


async def _status_after_load(
    app: Starlette, wait: tuple[str, ...]
) -> httpx.Response:
    """Enter the app lifespan, wait for ``wait`` owners to be ready, GET /status."""
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://gateway.test"
        ) as client:
            for owner in wait:
                await asyncio.wait_for(app.state.owners[owner].ready.wait(), timeout=15)
            return await client.get("/status")


async def _list_owner(http_client: httpx.AsyncClient, owner: str) -> set[str]:
    """Drive an MCP Streamable HTTP session and return the owner's resource URIs."""
    url = f"http://gateway.test/{owner}/mcp"
    async with streamable_http_client(url, http_client=http_client) as (
        read,
        write,
        _get_session_id,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_resources()
            return {str(r.uri) for r in listed.resources}


def test_restart_with_healthy_checkout_and_source_down_serves_stale(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """AC#1: a restart into a git outage serves the last-good checkout, stale."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    cache_dir = tmp_path / "cache"
    # First run: source up -> clone a healthy checkout, note its served SHA.
    app1 = create_app(_registry(source), cache_dir)
    good = asyncio.run(_status_after_load(app1, ("acme",))).json()["owners"]["acme"]
    good_commit = good["served_commit"]
    assert good["state"] == "serving" and good["source_available"] is True

    # The git source becomes unreachable (its bare repo is gone).
    shutil.rmtree(source.bare_dir)

    # Restart: the same cache volume persists; the source is down.
    app2 = create_app(_registry(source), cache_dir)
    entry = asyncio.run(_status_after_load(app2, ("acme",))).json()["owners"]["acme"]

    assert entry["state"] == "serving"  # degraded to stale-but-served, not failed
    assert entry["source_available"] is False
    assert entry["stale"] is True
    assert entry["served_commit"] == good_commit  # exactly the pre-outage SHA
    assert entry["last_pull_error"] is not None
    # Never *successfully* pulled this run, but an attempt was made and recorded.
    assert entry["last_pulled_at"] is None
    assert entry["last_pull_attempt_at"] is not None


def test_corrupt_checkout_with_source_up_reclones_clean(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """AC#2: a corrupt checkout with the source up is discarded and re-cloned."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    cache_dir = tmp_path / "cache"
    app1 = create_app(_registry(source), cache_dir)
    asyncio.run(_status_after_load(app1, ("acme",)))

    # Corrupt the persisted checkout so `git rev-parse HEAD` fails.
    shutil.rmtree(cache_dir / "acme" / ".git")

    app2 = create_app(_registry(source), cache_dir)
    entry = asyncio.run(_status_after_load(app2, ("acme",))).json()["owners"]["acme"]

    assert entry["state"] == "serving"
    assert entry["source_available"] is True
    assert entry["stale"] is False
    assert entry["served_commit"] is not None
    int(entry["served_commit"], 16)  # a real re-cloned commit SHA
    assert (cache_dir / "acme" / ".git").exists()  # a clean checkout was restored


def test_corrupt_checkout_with_source_down_fails(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """AC#2: a corrupt checkout with the source down has nothing safe to serve."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    cache_dir = tmp_path / "cache"
    app1 = create_app(_registry(source), cache_dir)
    asyncio.run(_status_after_load(app1, ("acme",)))

    shutil.rmtree(cache_dir / "acme" / ".git")  # corrupt
    shutil.rmtree(source.bare_dir)  # source down

    app2 = create_app(_registry(source), cache_dir)
    entry = asyncio.run(_status_after_load(app2, ("acme",))).json()["owners"]["acme"]

    assert entry["state"] == "failed"  # corrupt content has no fallback value
    assert entry["served_commit"] is None
    assert entry["source_available"] is False
    assert entry["stale"] is False  # failed != stale: nothing is being served
    assert "error" in entry


def test_empty_volume_and_source_down_fails(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """AC#3: an empty volume with the source down fails (genuinely nothing to serve)."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    shutil.rmtree(source.bare_dir)  # source down before any clone ever runs

    app = create_app(_registry(source), tmp_path / "cache")  # empty volume
    entry = asyncio.run(_status_after_load(app, ("acme",))).json()["owners"]["acme"]

    assert entry["state"] == "failed"
    assert entry["served_commit"] is None
    assert entry["source_available"] is False
    assert entry["stale"] is False
    assert "error" in entry


def test_unset_token_with_healthy_checkout_serves_stale(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC#4: a missing south token with a healthy checkout serves stale."""
    monkeypatch.delenv("OKF_TOK_ABSENT", raising=False)
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    cache_dir = tmp_path / "cache"
    dest = cache_dir / "acme"
    # A real, healthy checkout already in the volume (as a prior run left it).
    clone_owner(source.url, source.ref, dest)
    good_commit = head_commit(dest)

    # The owner is configured for an authenticated host whose token env is unset:
    # can't-authenticate is treated as source-unavailable when content exists.
    creds = {
        "git.corp": Credential(token_env="OKF_TOK_ABSENT", token_user="x-token-auth")
    }
    registry = Registry(
        owners={"acme": OwnerSpec(url="https://git.corp/acme.git", ref="main")},
        credentials=creds,
    )
    app = create_app(registry, cache_dir)
    entry = asyncio.run(_status_after_load(app, ("acme",))).json()["owners"]["acme"]

    assert entry["state"] == "serving"
    assert entry["source_available"] is False
    assert entry["stale"] is True
    assert entry["served_commit"] == good_commit


def test_unset_token_with_empty_volume_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC#4: a missing south token with an empty volume fails (loud first-deploy)."""
    monkeypatch.delenv("OKF_TOK_ABSENT", raising=False)
    creds = {
        "git.corp": Credential(token_env="OKF_TOK_ABSENT", token_user="x-token-auth")
    }
    registry = Registry(
        owners={"acme": OwnerSpec(url="https://git.corp/acme.git", ref="main")},
        credentials=creds,
    )
    app = create_app(registry, tmp_path / "cache")  # empty volume
    entry = asyncio.run(_status_after_load(app, ("acme",))).json()["owners"]["acme"]

    assert entry["state"] == "failed"
    assert entry["source_available"] is False
    assert entry["served_commit"] is None


def test_outage_then_source_restored_self_heals(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """AC#5: after an outage, get_or_refresh flips source_available and advances."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    dest = tmp_path / "acme"
    clock = FakeClock()
    resolved = ResolvedOwner(owner="acme", url=source.url, ref=source.ref, ttl=60)

    async def scenario() -> (
        tuple[str | None, str, tuple[bool, str | None], tuple[bool, str | None]]
    ):
        # A prior run left a healthy checkout at C0.
        seed = OwnerCache(resolved, dest, clock=clock)
        await seed.load()
        c0 = seed.commit
        # The source advances to C1, then goes unreachable.
        c1 = push_commit(source, {"docs/reference.md": CHANGED_REFERENCE_DOC})
        offline = source.bare_dir.parent / "repo.git.offline"
        source.bare_dir.rename(offline)
        # Restart against the same checkout while the source is down -> serve C0.
        cache = OwnerCache(resolved, dest, clock=clock)
        await cache.load()
        stale = (cache.source_available, cache.commit)
        # The source returns; the next TTL request self-heals to C1.
        offline.rename(source.bare_dir)
        await cache.get_or_refresh(60)
        healed = (cache.source_available, cache.commit)
        return c0, c1, stale, healed

    c0, c1, stale, healed = asyncio.run(scenario())

    assert c0 != c1
    assert stale == (False, c0)  # served the last-good C0 during the outage
    assert healed == (True, c1)  # flipped source_available and advanced served_commit


def test_refresh_with_source_down_returns_502_and_keeps_serving(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """AC#6: POST /refresh answers 502 on a source outage yet the MCP path stays up."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(_registry(source), tmp_path / "cache")

    async def scenario() -> tuple[str, httpx.Response, set[str]]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                await asyncio.wait_for(
                    app.state.owners["acme"].ready.wait(), timeout=15
                )
                served = (await client.get("/status")).json()["owners"]["acme"][
                    "served_commit"
                ]
                # The source goes unreachable, then an explicit refresh is forced.
                shutil.rmtree(source.bare_dir)
                refresh = await client.post("/acme/refresh")
                # The MCP content path must still answer with the last-good content.
                uris = await _list_owner(client, "acme")
                return served, refresh, uris

    served, refresh, uris = asyncio.run(scenario())

    assert refresh.status_code == 502  # loud failure so a `curl --fail` script trips
    body = refresh.json()
    assert body["owner"] == "acme"
    assert body["source_available"] is False
    assert body["served_commit"] == served  # the still-served commit is reported
    assert body["error"]  # a non-empty (scrubbed) error string
    assert uris == EXPECTED_URIS  # MCP content requests still succeed during the outage


def test_status_exposes_offline_fields_with_scrubbed_error(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC#7: /status exposes the offline fields; a token in the error is scrubbed."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    cache_dir = tmp_path / "cache"
    # First run: a healthy checkout.
    app1 = create_app(_registry(source), cache_dir)
    good_commit = asyncio.run(_status_after_load(app1, ("acme",))).json()["owners"][
        "acme"
    ]["served_commit"]

    # Restart with a fetch that fails with an exception whose text embeds a token:
    # the /status render must scrub it out of last_pull_error.
    leaky_url = f"https://x-token-auth:{GIT_TOKEN_SECRET}@git.corp/acme.git"

    def leaky_fetch(
        checkout: Path,
        ref: str,
        url: str,
        *,
        credentials: Mapping[str, Credential] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        raise subprocess.CalledProcessError(
            128, ["git", "fetch", "--depth", "1", leaky_url, ref]
        )

    monkeypatch.setattr(owner_cache_module, "fetch_and_reset", leaky_fetch)

    app2 = create_app(_registry(source), cache_dir)
    entry = asyncio.run(_status_after_load(app2, ("acme",))).json()["owners"]["acme"]

    assert entry["state"] == "serving"
    # All four offline fields are exposed for the owner.
    assert entry["source_available"] is False
    assert entry["stale"] is True
    assert isinstance(entry["last_pull_attempt_at"], str)  # ISO 8601 attempt stamp
    assert entry["served_commit"] == good_commit
    # The scrubbed error never contains the token; the userinfo becomes ***@.
    assert GIT_TOKEN_SECRET not in entry["last_pull_error"]
    assert "***@git.corp" in entry["last_pull_error"]


def test_good_checkout_is_never_rmtreed_on_startup(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC#8: startup never discards a good checkout (only clone_owner rmtrees)."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    cache_dir = tmp_path / "cache"
    # First run: heal a checkout, then drop a sentinel to prove it is not recreated.
    app1 = create_app(_registry(source), cache_dir)
    asyncio.run(_status_after_load(app1, ("acme",)))
    sentinel = cache_dir / "acme" / ".git" / "OFFLINE_SENTINEL"
    sentinel.write_text("survive me")
    good_commit = head_commit(cache_dir / "acme")

    shutil.rmtree(source.bare_dir)  # source down

    clone_calls: list[str] = []
    real_clone = owner_cache_module.clone_owner

    def spy_clone(
        url: str,
        ref: str,
        dest: Path,
        *,
        credentials: Mapping[str, Credential] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Path:
        clone_calls.append(url)  # clone_owner is the ONLY function that rmtree's
        return real_clone(url, ref, dest, credentials=credentials, env=env)

    monkeypatch.setattr(owner_cache_module, "clone_owner", spy_clone)

    app2 = create_app(_registry(source), cache_dir)
    entry = asyncio.run(_status_after_load(app2, ("acme",))).json()["owners"]["acme"]

    assert clone_calls == []  # clone_owner (hence rmtree) never ran for a good checkout
    assert sentinel.exists()  # the persisted checkout survived untouched
    assert entry["state"] == "serving"
    assert entry["served_commit"] == good_commit


def test_get_or_refresh_during_outage_serves_stale_without_raising(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """A past-TTL get_or_refresh with the source down keeps serving the last-good
    build instead of raising, and stays stale so the next request re-attempts."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    dest = tmp_path / "acme"
    clock = FakeClock()
    resolved = ResolvedOwner(owner="acme", url=source.url, ref=source.ref, ttl=60)

    async def scenario() -> tuple[object, str | None, object, object, object]:
        cache = OwnerCache(resolved, dest, clock=clock)
        await cache.load()  # source up: fresh clone at C0 (last_pulled stamped at 0)
        good_server = cache.server
        good_commit = cache.commit
        shutil.rmtree(source.bare_dir)  # source goes down
        clock.advance(100)  # past ttl=60 -> the request attempts a pull
        served1 = await cache.get_or_refresh(60)  # must NOT raise
        after1 = (cache.source_available, cache.commit, cache.last_pulled)
        clock.advance(100)  # still stale: the failed attempt left last_pulled frozen
        served2 = await cache.get_or_refresh(60)  # re-attempts, still serves
        return good_server, good_commit, served1, served2, after1

    good_server, good_commit, served1, served2, after1 = asyncio.run(scenario())

    assert served1 is good_server  # same last-good build, no rebuild, no raise
    assert served2 is good_server  # every stale request keeps serving it
    # Stale flag set; the success clock stayed frozen at the load stamp (t=0), so
    # the owner remains past-TTL and re-attempts on the next request.
    assert after1 == (False, good_commit, 0.0)


def test_refresh_502_error_is_scrubbed_of_tokens(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC#6/#7: a token embedded in the source error is scrubbed from the 502 body."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    leaky_url = f"https://x-token-auth:{GIT_TOKEN_SECRET}@git.corp/acme.git"

    def leaky_fetch(
        checkout: Path,
        ref: str,
        url: str,
        *,
        credentials: Mapping[str, Credential] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        raise subprocess.CalledProcessError(128, ["git", "fetch", leaky_url, ref])

    app = create_app(_registry(source), tmp_path / "cache")

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                await asyncio.wait_for(
                    app.state.owners["acme"].ready.wait(), timeout=15
                )
                # The initial clone is done; make the forced fetch fail with a token.
                monkeypatch.setattr(owner_cache_module, "fetch_and_reset", leaky_fetch)
                return await client.post("/acme/refresh")

    refresh = asyncio.run(scenario())

    assert refresh.status_code == 502
    body = refresh.json()
    assert GIT_TOKEN_SECRET not in body["error"]  # the token never reaches the body
    assert "***@git.corp" in body["error"]  # userinfo redacted, host kept for debugging
