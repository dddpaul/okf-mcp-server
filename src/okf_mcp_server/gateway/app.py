"""Starlette app for the multi-owner Streamable HTTP gateway (US-002).

The gateway wraps the existing stdio core verbatim: for each registered owner it
shallow-clones the owner's repo, runs the unchanged ``load_docs`` and
``build_server`` against the checkout, and exposes the resulting MCP server over
Streamable HTTP at ``/{owner}/mcp``. The registry is the owner allowlist — a
request for an unregistered owner returns 404.

Owners are eager-cloned in independent background tasks at startup so ``GET
/healthz`` and already-cloned owners serve immediately; an owner whose clone is
still in flight resolves lazily when its first request awaits its readiness,
without blocking other owners or ``/healthz``. Auth, TTL refresh, and Docker
packaging arrive in later tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncIterator
from pathlib import Path

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from ..config import ServerConfig
from ..server import build_server, load_docs
from .git_source import clone_owner
from .registry import Registry, ResolvedOwner


class OwnerState:
    """Mutable runtime state for one registered owner.

    The clone/build runs in a background task; ``ready`` is set once the owner is
    either serving (``session_manager`` populated) or has failed (``error``
    populated). Requests await ``ready``, so an in-flight clone resolves lazily
    without blocking other owners.

    Attributes:
        resolved: The owner's resolved config (url, ref, ttl).
        dest: Cache directory the owner's repo is cloned into.
        ready: Set when the owner is serving or has permanently failed to load.
        session_manager: The owner's MCP session manager once running, else None.
        checkout: The clone checkout path once cloned, else None.
        error: The clone/build exception if the owner failed to load, else None.
    """

    def __init__(self, resolved: ResolvedOwner, dest: Path) -> None:
        self.resolved = resolved
        self.dest = dest
        self.ready = asyncio.Event()
        self.session_manager: StreamableHTTPSessionManager | None = None
        self.checkout: Path | None = None
        self.error: Exception | None = None


def _clone_and_build(resolved: ResolvedOwner, dest: Path) -> tuple[Path, Server]:
    """Shallow-clone the owner and build its MCP server (runs in a worker thread).

    Executes the blocking git clone and file scan off the event loop so a slow
    clone never stalls ``/healthz`` or other owners.

    Args:
        resolved: The owner's resolved config.
        dest: Target checkout directory.

    Returns:
        The checkout path and the built MCP :class:`Server`.
    """
    checkout = clone_owner(resolved.url, resolved.ref, dest)
    server_config = ServerConfig(owner=resolved.owner, roots=(checkout,))
    docs = load_docs(server_config)
    return checkout, build_server(docs)


async def _serve_owner(state: OwnerState, shutdown: asyncio.Event) -> None:
    """Clone and serve one owner for the app's lifespan.

    Clones and builds the owner off the event loop, then holds the owner's MCP
    session manager open until ``shutdown`` is set. A clone/build failure is
    recorded on ``state`` and isolated to this owner — it never propagates to
    other owners or ``/healthz``.

    Args:
        state: The owner's runtime state to populate.
        shutdown: Event signalled when the app is shutting down.
    """
    try:
        checkout, mcp_server = await asyncio.to_thread(
            _clone_and_build, state.resolved, state.dest
        )
    except Exception as exc:  # isolate a single owner's clone/build failure
        state.error = exc
        state.ready.set()
        print(
            f"okf-mcp-gateway: owner {state.resolved.owner!r} failed to load: {exc}",
            file=sys.stderr,
        )
        return
    session_manager = StreamableHTTPSessionManager(app=mcp_server)
    async with session_manager.run():
        state.checkout = checkout
        state.session_manager = session_manager
        state.ready.set()
        await shutdown.wait()


class _MCPRouter:
    """ASGI endpoint dispatching ``/{owner}/mcp`` to the owner's session manager.

    Starlette treats a bare callable object (not a function) as a raw ASGI app,
    so every HTTP method the Streamable HTTP transport uses — GET, POST, and
    DELETE — reaches this endpoint. The owner segment is read from the route's
    ``path_params``; unregistered owners get 404.
    """

    def __init__(self, owners: dict[str, OwnerState]) -> None:
        self._owners = owners

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        owner = scope["path_params"]["owner"]
        state = self._owners.get(owner)
        if state is None:
            await PlainTextResponse(f"unknown owner: {owner}", status_code=404)(
                scope, receive, send
            )
            return
        await state.ready.wait()  # lazy resolve: wait out an in-flight clone
        if state.session_manager is None:
            await PlainTextResponse(
                f"owner {owner} is unavailable", status_code=503
            )(scope, receive, send)
            return
        await state.session_manager.handle_request(scope, receive, send)


def create_app(registry: Registry, cache_dir: Path) -> Starlette:
    """Build the multi-owner gateway app from a validated registry.

    Each registered owner is eager-cloned in its own background task for the
    app's lifespan; ``/healthz`` and ready owners serve immediately while any
    in-flight clone resolves lazily on first request.

    Args:
        registry: Validated registry; its owners form the allowlist.
        cache_dir: Directory under which per-owner checkouts are written.

    Returns:
        A configured Starlette application.
    """
    owners: dict[str, OwnerState] = {}
    for name in registry.owners:
        resolved = registry.resolve(name)
        if resolved is None:  # unreachable: name comes from registry.owners
            continue
        owners[name] = OwnerState(resolved, cache_dir / name)

    async def healthz(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        shutdown = asyncio.Event()
        tasks = [
            asyncio.create_task(_serve_owner(state, shutdown), name=f"clone:{name}")
            for name, state in owners.items()
        ]
        try:
            yield
        finally:
            shutdown.set()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/{owner}/mcp", endpoint=_MCPRouter(owners)),
        ],
        lifespan=lifespan,
    )
    # Surface per-owner state for tests/introspection.
    app.state.owners = owners
    return app


__all__ = ["OwnerState", "create_app"]
