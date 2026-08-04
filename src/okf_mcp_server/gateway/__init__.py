"""okf-mcp-gateway — additive MCP Streamable HTTP gateway over the stdio core.

This package wraps the existing stdio engine (``load_docs`` / ``build_server``)
without modifying it, serving each registered owner over MCP Streamable HTTP at
``/{owner}/mcp``. Owners are declared in ``servers.yaml`` (the owner allowlist);
a shared north bearer token gates consumers and per-host tokens authenticate the
gateway to git hosts. Docker packaging arrives in a later task.
"""

from __future__ import annotations

from .app import BearerAuthMiddleware, create_app
from .config import GatewayConfig
from .git_source import CredentialError, build_authenticated_url
from .owner_cache import OwnerCache, RefreshResult, RefreshUnavailable
from .registry import Registry, RegistryError, load_registry

__all__ = [
    "BearerAuthMiddleware",
    "CredentialError",
    "GatewayConfig",
    "OwnerCache",
    "RefreshResult",
    "RefreshUnavailable",
    "Registry",
    "RegistryError",
    "build_authenticated_url",
    "create_app",
    "load_registry",
]
