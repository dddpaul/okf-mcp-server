"""US-002: multi-owner registry routing over Streamable HTTP.

Every test is offline — ``file://`` bare-repo fixtures are the clone sources and
the Starlette app is driven in-process over ``httpx.ASGITransport``. No live git
host, network, or secrets are involved.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from conftest import GitRepoFixture
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from okf_mcp_server.gateway import Registry, create_app
from okf_mcp_server.gateway import app as app_module
from okf_mcp_server.gateway.git_source import clone_owner
from okf_mcp_server.gateway.registry import OwnerSpec

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

NOT_EXPORTED = """# Just a readme

No frontmatter, so it must not be served.
"""

FIXTURE_FILES = {
    "docs/reference.md": REFERENCE_DOC,
    "design/adr.md": DECISION_DOC,
    "README.md": NOT_EXPORTED,
}


def _expected_uris(owner: str) -> set[str]:
    return {
        f"knowledge://{owner}/reference-doc/gw-ref-1",
        f"knowledge://{owner}/architecture-decision/gw-adr-1",
    }


def _registry_for(sources: dict[str, GitRepoFixture]) -> Registry:
    return Registry(
        owners={
            name: OwnerSpec(url=src.url, ref=src.ref) for name, src in sources.items()
        }
    )


def test_healthz_returns_200(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(_registry_for({"acme": source}), tmp_path / "cache")

    response = asyncio.run(_get(app, "/healthz"))

    assert response.status_code == 200
    assert response.text == "ok"


def test_clone_owner_produces_shallow_checkout(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    dest = tmp_path / "cache" / "acme"

    checkout = clone_owner(source.url, source.ref, dest)

    assert checkout == dest
    assert (checkout / ".git").exists()
    assert (checkout / "docs" / "reference.md").is_file()
    depth = subprocess.run(
        ["git", "-C", str(checkout), "rev-list", "--count", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert depth.stdout.strip() == "1"  # --depth 1 => single commit


def test_two_owners_served_independently(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    alpha = make_bare_repo(FIXTURE_FILES, ref="main")
    beta = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(_registry_for({"alpha": alpha, "beta": beta}), tmp_path / "cache")

    # Both owners are driven within one app lifespan, as in production.
    async def scenario() -> tuple[set[str], dict[str, str | None], set[str]]:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as http_client:
                alpha_uris, alpha_contents = await _list_and_read(http_client, "alpha")
                beta_uris, _beta_contents = await _list_and_read(http_client, "beta")
                return alpha_uris, alpha_contents, beta_uris

    alpha_uris, alpha_contents, beta_uris = asyncio.run(scenario())

    # Each owner is served at its own path with owner-scoped, disjoint URIs.
    assert alpha_uris == _expected_uris("alpha")
    assert beta_uris == _expected_uris("beta")
    assert alpha_uris.isdisjoint(beta_uris)
    assert "Body of the gateway reference doc." in (
        alpha_contents["knowledge://alpha/reference-doc/gw-ref-1"] or ""
    )


def test_unregistered_owner_returns_404(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(_registry_for({"acme": source}), tmp_path / "cache")

    response = asyncio.run(_get(app, "/ghost/mcp"))

    assert response.status_code == 404


def test_content_originates_from_git_clone_not_a_mount(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    cache_dir = tmp_path / "cache"
    app = create_app(_registry_for({"acme": source}), cache_dir)

    # Drive one request so the owner's background clone resolves.
    asyncio.run(_drive_mcp(app, "acme"))
    checkout = app.state.owners["acme"].checkout

    assert checkout is not None
    # The served checkout is a real clone inside the gateway cache dir...
    assert checkout == cache_dir / "acme"
    assert checkout.is_relative_to(cache_dir)
    assert (checkout / ".git").exists()
    # ...distinct from both the fixture working tree and the bare source repo...
    assert checkout != source.work_dir
    assert checkout != source.bare_dir
    # ...and its git origin is the file:// bare repo it was cloned from.
    origin = subprocess.run(
        ["git", "-C", str(checkout), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert origin.stdout.strip() == source.url


def test_slow_owner_does_not_block_healthz_or_other_owners(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow = make_bare_repo(FIXTURE_FILES, ref="main")
    fast = make_bare_repo(FIXTURE_FILES, ref="main")
    release = threading.Event()
    real_clone = clone_owner

    def gated_clone(url: str, ref: str, dest: Path) -> Path:
        # Block the slow owner's clone (in a worker thread) until released.
        if url == slow.url:
            release.wait(timeout=30)
        return real_clone(url, ref, dest)

    monkeypatch.setattr(app_module, "clone_owner", gated_clone)
    app = create_app(_registry_for({"slow": slow, "fast": fast}), tmp_path / "cache")

    async def scenario() -> None:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as http_client:
                try:
                    # /healthz answers immediately though the slow clone is stuck.
                    health = await http_client.get("/healthz")
                    assert health.status_code == 200

                    # The fast owner resolves and serves while slow is in flight.
                    await asyncio.wait_for(
                        app.state.owners["fast"].ready.wait(), timeout=10
                    )
                    assert not app.state.owners["slow"].ready.is_set()
                    uris = await _list_owner(http_client, "fast")
                    assert uris == _expected_uris("fast")
                finally:
                    release.set()  # let the slow clone finish for clean shutdown

    asyncio.run(scenario())


async def _get(app: Starlette, path: str) -> httpx.Response:
    """GET ``path`` in-process, with the app lifespan running (app is 'up')."""
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://gateway.test"
        ) as http_client:
            return await http_client.get(path)


async def _drive_mcp(
    app: Starlette, owner: str
) -> tuple[set[str], dict[str, str | None]]:
    """Drive an MCP Streamable HTTP session against the in-process app."""
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://gateway.test"
        ) as http_client:
            return await _list_and_read(http_client, owner)


async def _list_and_read(
    http_client: httpx.AsyncClient, owner: str
) -> tuple[set[str], dict[str, str | None]]:
    url = f"http://gateway.test/{owner}/mcp"
    async with streamable_http_client(url, http_client=http_client) as (
        read,
        write,
        _get_session_id,
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_resources()
            uris = {str(r.uri) for r in listed.resources}
            contents: dict[str, str | None] = {}
            for resource in listed.resources:
                result = await session.read_resource(resource.uri)
                payload = result.contents[0]
                contents[str(resource.uri)] = getattr(payload, "text", None)
            return uris, contents


async def _list_owner(http_client: httpx.AsyncClient, owner: str) -> set[str]:
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
