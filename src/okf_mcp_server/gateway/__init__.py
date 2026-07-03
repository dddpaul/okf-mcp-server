"""okf-mcp-gateway — additive MCP Streamable HTTP gateway over the stdio core.

This package wraps the existing stdio engine (``load_docs`` / ``build_server``)
without modifying it, serving each registered owner over MCP Streamable HTTP at
``/{owner}/mcp``. Owners are declared in ``servers.yaml`` (the owner allowlist);
auth, TTL refresh, and Docker packaging arrive in later tasks.
"""

from __future__ import annotations

from .app import create_app
from .config import GatewayConfig
from .owner_cache import OwnerCache, RefreshResult
from .registry import Registry, RegistryError, load_registry

__all__ = [
    "GatewayConfig",
    "OwnerCache",
    "RefreshResult",
    "Registry",
    "RegistryError",
    "create_app",
    "load_registry",
]
