"""Starlette app for the single-owner Streamable HTTP gateway (US-001).

The gateway wraps the existing stdio core verbatim: it shallow-clones one
owner's repo, runs the unchanged ``load_docs`` and ``build_server`` against the
checkout, and exposes the resulting MCP server over Streamable HTTP at
``/{owner}/mcp`` alongside an unauthenticated ``GET /healthz``. Multi-owner
routing, auth, TTL refresh, and Docker packaging arrive in later tasks.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from ..config import ServerConfig
from ..server import build_server, load_docs
from .config import GatewayConfig
from .git_source import clone_owner


class _MCPHandler:
    """ASGI endpoint bridging a Starlette route to an MCP session manager.

    Starlette treats a bare callable object (not a function) as a raw ASGI app,
    so every HTTP method the Streamable HTTP transport uses — GET, POST, and
    DELETE — reaches ``handle_request`` instead of defaulting to GET-only.
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self._session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._session_manager.handle_request(scope, receive, send)


def create_app(config: GatewayConfig) -> Starlette:
    """Build the single-owner gateway app from a shallow git clone.

    Shallow-clones the owner repo into ``config.cache_dir``, loads its docs and
    builds the MCP server through the unchanged core, and wires ``/healthz`` and
    ``/{owner}/mcp``. The MCP session manager runs for the app's lifespan.

    Args:
        config: Resolved single-owner gateway configuration.

    Returns:
        A configured Starlette application.
    """
    checkout = clone_owner(config.git_url, config.ref, config.cache_dir / config.owner)
    server_config = ServerConfig(owner=config.owner, roots=(checkout,))
    docs = load_docs(server_config)
    mcp_server = build_server(docs)
    session_manager = StreamableHTTPSessionManager(app=mcp_server)

    async def healthz(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route(f"/{config.owner}/mcp", endpoint=_MCPHandler(session_manager)),
        ],
        lifespan=lifespan,
    )
    # Surface provenance for tests/introspection: content came from this checkout.
    app.state.owner = config.owner
    app.state.checkout = checkout
    return app


__all__ = ["create_app"]
