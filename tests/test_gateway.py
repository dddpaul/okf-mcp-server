"""US-001 vertical slice: serve one git-sourced owner over Streamable HTTP.

Every test is offline — a ``file://`` bare-repo fixture is the clone source and
the Starlette app is driven in-process over ``httpx.ASGITransport``. No live
git host, network, or secrets are involved.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
from conftest import GitRepoFixture
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette

from okf_mcp_server.gateway import GatewayConfig, create_app
from okf_mcp_server.gateway.git_source import clone_owner

OWNER = "acme"

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

EXPECTED_URIS = {
    f"knowledge://{OWNER}/reference-doc/gw-ref-1",
    f"knowledge://{OWNER}/architecture-decision/gw-adr-1",
}


def _build_app(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> tuple[Starlette, GatewayConfig, GitRepoFixture]:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    config = GatewayConfig(
        owner=OWNER,
        git_url=source.url,
        ref=source.ref,
        cache_dir=tmp_path / "cache",
    )
    return create_app(config), config, source


def test_healthz_returns_200(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    app, _config, _source = _build_app(make_bare_repo, tmp_path)
    response = asyncio.run(_get(app, "/healthz"))
    assert response.status_code == 200
    assert response.text == "ok"


def test_clone_owner_produces_shallow_checkout(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    dest = tmp_path / "cache" / OWNER

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


def test_content_originates_from_git_clone_not_a_mount(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    app, config, source = _build_app(make_bare_repo, tmp_path)

    checkout: Path = app.state.checkout
    # The served checkout is a real clone inside the gateway cache dir...
    assert checkout == config.cache_dir / OWNER
    assert checkout.is_relative_to(config.cache_dir)
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


def test_mcp_session_lists_and_reads_owner_docs(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    app, _config, _source = _build_app(make_bare_repo, tmp_path)
    uris, contents = asyncio.run(_drive_mcp(app, OWNER))

    assert uris == EXPECTED_URIS
    assert "Body of the gateway reference doc." in (
        contents[f"knowledge://{OWNER}/reference-doc/gw-ref-1"] or ""
    )
    assert "The gateway decision body." in (
        contents[f"knowledge://{OWNER}/architecture-decision/gw-adr-1"] or ""
    )


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
