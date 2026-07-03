"""Starlette app for the multi-owner Streamable HTTP gateway (US-002, US-003).

The gateway wraps the existing stdio core verbatim: for each registered owner it
shallow-clones the owner's repo, runs the unchanged ``load_docs`` and
``build_server`` against the checkout, and exposes the resulting MCP server over
Streamable HTTP at ``/{owner}/mcp``. The registry is the owner allowlist — a
request for an unregistered owner returns 404.

Owners are eager-cloned in independent background tasks at startup so ``GET
/healthz`` and already-cloned owners serve immediately; an owner whose clone is
still in flight resolves lazily when its first request awaits its readiness,
without blocking other owners or ``/healthz``.

Content is kept freshly-enough by a per-owner TTL cache (US-003): each
``/{owner}/mcp`` request first pulls the owner if it is staler than its TTL, and
``POST /{owner}/refresh`` forces an immediate pull. When a pull rebuilds an
owner's server, the owner's session manager is re-pointed at the fresh build so
subsequent MCP sessions serve the new content. Auth and Docker packaging arrive
in later tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from .owner_cache import OwnerCache
from .registry import Registry


class OwnerState:
    """Serving state for one registered owner, wrapping its content cache.

    The clone/build runs in a background task; ``ready`` is set once the owner is
    either serving (``session_manager`` populated) or has failed (``error``
    populated). Requests await ``ready``, so an in-flight clone resolves lazily
    without blocking other owners.

    Attributes:
        cache: The owner's TTL content cache (checkout, docs, built server, lock).
        ready: Set when the owner is serving or has permanently failed to load.
        session_manager: The owner's MCP session manager once running, else None.
        error: The clone/build exception if the owner failed to load, else None.
    """

    def __init__(self, cache: OwnerCache) -> None:
        self.cache = cache
        self.ready = asyncio.Event()
        self.session_manager: StreamableHTTPSessionManager | None = None
        self.error: Exception | None = None

    @property
    def checkout(self) -> Path | None:
        """The owner's checkout path once cloned, else ``None`` (from the cache)."""
        return self.cache.checkout


async def _serve_owner(state: OwnerState, shutdown: asyncio.Event) -> None:
    """Clone and serve one owner for the app's lifespan.

    Clones and builds the owner off the event loop via its cache, then holds the
    owner's MCP session manager open until ``shutdown`` is set. A clone/build
    failure is recorded on ``state`` and isolated to this owner — it never
    propagates to other owners or ``/healthz``.

    Args:
        state: The owner's runtime state to populate.
        shutdown: Event signalled when the app is shutting down.
    """
    try:
        await state.cache.load()
    except Exception as exc:  # isolate a single owner's clone/build failure
        state.error = exc
        state.ready.set()
        print(
            f"okf-mcp-gateway: owner {state.cache.resolved.owner!r} failed to "
            f"load: {exc}",
            file=sys.stderr,
        )
        return
    server = state.cache.server
    assert server is not None  # a successful load() always sets the server
    session_manager = StreamableHTTPSessionManager(app=server)
    async with session_manager.run():
        state.session_manager = session_manager
        state.ready.set()
        await shutdown.wait()


class _MCPRouter:
    """ASGI endpoint dispatching ``/{owner}/mcp`` to the owner's session manager.

    Starlette treats a bare callable object (not a function) as a raw ASGI app,
    so every HTTP method the Streamable HTTP transport uses — GET, POST, and
    DELETE — reaches this endpoint. The owner segment is read from the route's
    ``path_params``; unregistered owners get 404. Before dispatch the owner is
    TTL-refreshed and the session manager is re-pointed at the current build so a
    new MCP session serves freshly-enough content.
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
        server = await state.cache.get_or_refresh(state.cache.resolved.ttl)
        # New sessions bind whatever `app` is at connect time; point it at the
        # freshest build so a post-refresh session serves the new content.
        state.session_manager.app = server
        await state.session_manager.handle_request(scope, receive, send)


def create_app(
    registry: Registry,
    cache_dir: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> Starlette:
    """Build the multi-owner gateway app from a validated registry.

    Each registered owner is eager-cloned in its own background task for the
    app's lifespan; ``/healthz`` and ready owners serve immediately while any
    in-flight clone resolves lazily on first request. Each ``/{owner}/mcp``
    request is TTL-gated and ``POST /{owner}/refresh`` forces a pull.

    Args:
        registry: Validated registry; its owners form the allowlist.
        cache_dir: Directory under which per-owner checkouts are written.
        clock: Monotonic-seconds source threaded into every owner's TTL cache;
            injectable so tests drive staleness deterministically.

    Returns:
        A configured Starlette application.
    """
    owners: dict[str, OwnerState] = {}
    for name in registry.owners:
        resolved = registry.resolve(name)
        if resolved is None:  # unreachable: name comes from registry.owners
            continue
        cache = OwnerCache(resolved, cache_dir / name, clock=clock)
        owners[name] = OwnerState(cache)

    async def healthz(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def refresh(request: Request) -> JSONResponse:
        owner = request.path_params["owner"]
        state = owners.get(owner)
        if state is None:
            return JSONResponse(
                {"error": f"unknown owner: {owner}"}, status_code=404
            )
        await state.ready.wait()  # lazy resolve: wait out an in-flight clone
        if state.session_manager is None:
            return JSONResponse(
                {"error": f"owner {owner} is unavailable"}, status_code=503
            )
        result = await state.cache.force_refresh()
        # Point the transport at the rebuilt server for subsequent MCP sessions.
        server = state.cache.server
        assert server is not None  # force_refresh() always leaves a built server
        state.session_manager.app = server
        return JSONResponse(
            {
                "owner": result.owner,
                "ref": result.ref,
                "commit": result.commit,
                "docs_loaded": result.docs_loaded,
            }
        )

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
            Route("/{owner}/refresh", refresh, methods=["POST"]),
            Route("/{owner}/mcp", endpoint=_MCPRouter(owners)),
        ],
        lifespan=lifespan,
    )
    # Surface per-owner state for tests/introspection.
    app.state.owners = owners
    return app


__all__ = ["OwnerState", "create_app"]
