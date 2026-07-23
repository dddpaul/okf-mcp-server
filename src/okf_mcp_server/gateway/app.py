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
subsequent MCP sessions serve the new content.

North consumer auth (US-004) is a single ASGI choke point,
:class:`BearerAuthMiddleware`: when a shared token is configured, every route
except ``GET /healthz`` requires ``Authorization: Bearer <token>`` and is
rejected with 401 otherwise. It runs outside the router, so an unauthenticated
caller is turned away before owner routing and cannot even probe which owners
exist. South git-host auth lives in :mod:`.git_source`; Docker packaging arrives
in a later task.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import re
import secrets
import sys
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import yaml
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .owner_cache import OwnerCache
from .registry import Registry

# Redacts URL userinfo (``user:token@``) so a token embedded in a clone URL cannot
# survive into a rendered ``/status`` error message. Host and path are kept for
# debugging; only the ``user:token`` pair is dropped.
_CRED_IN_URL = re.compile(r"(?P<scheme>https?://)[^/@\s]+@")


def _scrub_credentials(text: str) -> str:
    """Redact ``scheme://user:token@`` userinfo from ``text`` (host/path survive)."""
    return _CRED_IN_URL.sub(r"\g<scheme>***@", text)


def _iso_utc(epoch: float) -> str:
    """Render epoch ``seconds`` as an ISO 8601 UTC string (``...Z``, whole seconds)."""
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


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


class BearerAuthMiddleware:
    """Single north auth choke point: shared bearer token on all but ``/healthz``.

    Wraps the whole app outside the router, so a request with a missing or wrong
    ``Authorization: Bearer <token>`` header is rejected with 401 before any owner
    routing runs — an unauthenticated caller cannot distinguish a registered owner
    from an unknown one. ``GET /healthz`` is exempt so container health checks
    stay open. The token comparison is constant-time to avoid leaking it by timing.

    Attributes:
        token: The expected shared bearer token.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/healthz":
            await self._app(scope, receive, send)
            return
        if not self._authorized(scope):
            response = PlainTextResponse(
                "unauthorized",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        """Return whether the request carries the expected ``Bearer`` token."""
        header = Headers(scope=scope).get("authorization", "")
        scheme, _, credential = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        return secrets.compare_digest(
            credential.encode("utf-8"), self._token.encode("utf-8")
        )


def _effective_config(
    registry: Registry,
    *,
    servers_path: Path | None,
    cache_dir: Path,
    host: str | None,
    port: int | None,
    auth_required: bool,
) -> dict[str, Any]:
    """Assemble the gateway's effective runtime configuration for ``GET /config``.

    The result is a JSON/YAML-ready mapping — every value is a ``str``, ``int``,
    ``bool``, ``None``, or a nested mapping of those. Each owner's ``ref``/``ttl``
    is resolved against the ``defaults`` block (via :meth:`Registry.resolve`), so
    an owner that omits them reflects the defaults. The ``credentials`` block
    exposes only each host's token *environment-variable name* and username; the
    secret token value is never read from the environment nor emitted.

    Args:
        registry: The validated registry backing this app.
        servers_path: Path to the loaded ``servers.yaml`` (``None`` if unset).
        cache_dir: Directory under which per-owner checkouts are written.
        host: Bind host reported in the process block (``None`` if unset).
        port: Bind port reported in the process block (``None`` if unset).
        auth_required: Whether a north token gates every route but ``/healthz``.

    Returns:
        The effective configuration as a JSON/YAML-serializable mapping.
    """
    owners: dict[str, dict[str, Any]] = {}
    for name in registry.owners:
        resolved = registry.resolve(name)
        if resolved is None:  # unreachable: name comes from registry.owners
            continue
        owners[name] = {"url": resolved.url, "ref": resolved.ref, "ttl": resolved.ttl}
    credentials = {
        host_name: {"token_env": cred.token_env, "token_user": cred.token_user}
        for host_name, cred in registry.credentials.items()
    }
    return {
        "process": {
            "servers_path": None if servers_path is None else str(servers_path),
            "cache_dir": str(cache_dir),
            "host": host,
            "port": port,
            "auth_required": auth_required,
        },
        "defaults": {"ref": registry.defaults.ref, "ttl": registry.defaults.ttl},
        "owners": owners,
        "credentials": credentials,
    }


def _owner_status(owners: dict[str, OwnerState]) -> dict[str, Any]:
    """Assemble live per-owner runtime state for ``GET /status``.

    A pure read of current in-memory state — it never triggers a pull or any
    side effect. Each owner's ``state`` is derived from its :class:`OwnerState`:
    an owner whose clone is still in flight is ``"loading"``; a ready owner with a
    running session manager is ``"serving"``; a ready owner without one is
    ``"failed"`` (its ``error`` is rendered with render-time credential scrubbing,
    so a token-bearing clone exception cannot leak). ``served_commit`` is the git
    SHA of the working copy the gateway currently serves for the owner — the
    provenance signal a downstream consumer checks to confirm a merge→push→pull
    chain ran. It, along with ``docs_loaded``/``last_pulled_*``, is read straight
    from the owner's cache, so they are ``null``/``0`` until a successful load
    populates them. The owner ``url`` is deliberately not echoed — that is config,
    and omitting it keeps a redaction surface off this endpoint.

    Args:
        owners: The app's per-owner runtime states, keyed by owner name.

    Returns:
        A JSON/YAML-serializable mapping with a top-level ``summary`` counts block
        and an ``owners`` map of per-owner state.
    """
    owner_map: dict[str, dict[str, Any]] = {}
    counts = {"serving": 0, "loading": 0, "failed": 0}
    for name, state in owners.items():
        cache = state.cache
        if not state.ready.is_set():
            owner_state = "loading"
        elif state.session_manager is not None:
            owner_state = "serving"
        else:
            owner_state = "failed"
        counts[owner_state] += 1
        # Read the two stamps into locals: no await runs before they are used, so
        # the pair is a consistent snapshot even if a pull applies concurrently.
        last_pulled = cache.last_pulled
        last_pulled_wall = cache.last_pulled_wall
        entry: dict[str, Any] = {
            "state": owner_state,
            "ref": cache.resolved.ref,
            "served_commit": cache.commit,
            "docs_loaded": len(cache.docs),
            "last_pulled_at": (
                None if last_pulled_wall is None else _iso_utc(last_pulled_wall)
            ),
            "last_pulled_age_seconds": (
                None if last_pulled is None else int(cache._clock() - last_pulled)
            ),
        }
        if owner_state == "failed":
            error = state.error
            entry["error"] = {
                "type": type(error).__name__ if error is not None else "UnknownError",
                "message": _scrub_credentials(str(error)) if error is not None else "",
            }
        owner_map[name] = entry
    return {
        "summary": {
            "total": len(owners),
            "serving": counts["serving"],
            "loading": counts["loading"],
            "failed": counts["failed"],
        },
        "owners": owner_map,
    }


def create_app(
    registry: Registry,
    cache_dir: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
    auth_token: str | None = None,
    servers_path: Path | None = None,
    host: str | None = None,
    port: int | None = None,
) -> Starlette:
    """Build the multi-owner gateway app from a validated registry.

    Each registered owner is eager-cloned in its own background task for the
    app's lifespan; ``/healthz`` and ready owners serve immediately while any
    in-flight clone resolves lazily on first request. Each ``/{owner}/mcp``
    request is TTL-gated and ``POST /{owner}/refresh`` forces a pull. ``GET
    /config`` prints the effective configuration (JSON, or YAML with
    ``?format=yaml``); like every route but ``/healthz`` it sits behind the north
    token, so it never leaks config to an anonymous caller. ``GET /status`` is its
    live-runtime sibling: a pure read (never a pull) reporting each owner's state,
    served in the same JSON/``?format=yaml`` shape and behind the same token.

    Args:
        registry: Validated registry; its owners form the allowlist and its
            per-host ``credentials`` are injected into each owner's clone/fetch.
        cache_dir: Directory under which per-owner checkouts are written.
        clock: Monotonic-seconds source threaded into every owner's TTL cache;
            injectable so tests drive staleness deterministically.
        wall_clock: Absolute wall-clock (epoch seconds) source threaded into every
            owner's cache; stamped at each pull and rendered as ``last_pulled_at``
            by ``GET /status``. Injectable so tests assert an exact timestamp.
        auth_token: Shared north bearer token; when set, every route except
            ``GET /healthz`` requires it. ``None`` (the default) leaves the app
            open, which the console entry point forbids in production.
        servers_path: Path to the loaded ``servers.yaml``, reported by
            ``GET /config``; ``None`` (the default) renders as null there.
        host: Bind host reported by ``GET /config``; ``None`` renders as null.
        port: Bind port reported by ``GET /config``; ``None`` renders as null.

    Returns:
        A configured Starlette application.
    """
    owners: dict[str, OwnerState] = {}
    for name in registry.owners:
        resolved = registry.resolve(name)
        if resolved is None:  # unreachable: name comes from registry.owners
            continue
        cache = OwnerCache(
            resolved,
            cache_dir / name,
            clock=clock,
            wall_clock=wall_clock,
            credentials=registry.credentials,
        )
        owners[name] = OwnerState(cache)

    async def healthz(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    async def config(request: Request) -> Response:
        fmt = request.query_params.get("format", "json").lower()
        if fmt not in ("json", "yaml"):
            return JSONResponse(
                {"error": f"unsupported format {fmt!r}; use 'json' or 'yaml'"},
                status_code=400,
            )
        effective = _effective_config(
            registry,
            servers_path=servers_path,
            cache_dir=cache_dir,
            host=host,
            port=port,
            auth_required=bool(auth_token),
        )
        if fmt == "yaml":
            body = yaml.safe_dump(effective, sort_keys=False)
            return PlainTextResponse(body, media_type="application/yaml")
        return JSONResponse(effective)

    async def status(request: Request) -> Response:
        fmt = request.query_params.get("format", "json").lower()
        if fmt not in ("json", "yaml"):
            return JSONResponse(
                {"error": f"unsupported format {fmt!r}; use 'json' or 'yaml'"},
                status_code=400,
            )
        payload = _owner_status(owners)
        if fmt == "yaml":
            body = yaml.safe_dump(payload, sort_keys=False)
            return PlainTextResponse(body, media_type="application/yaml")
        return JSONResponse(payload)

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

    middleware = (
        [Middleware(BearerAuthMiddleware, token=auth_token)] if auth_token else []
    )
    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/config", config, methods=["GET"]),
            Route("/status", status, methods=["GET"]),
            Route("/{owner}/refresh", refresh, methods=["POST"]),
            Route("/{owner}/mcp", endpoint=_MCPRouter(owners)),
        ],
        middleware=middleware,
        lifespan=lifespan,
    )
    # Surface per-owner state, auth posture, and process config for introspection.
    app.state.owners = owners
    app.state.auth_required = bool(auth_token)
    app.state.servers_path = servers_path
    app.state.host = host
    app.state.port = port
    return app


__all__ = ["BearerAuthMiddleware", "OwnerState", "create_app"]
