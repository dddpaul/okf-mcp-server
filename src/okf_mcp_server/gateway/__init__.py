"""okf-mcp-gateway — additive MCP Streamable HTTP gateway over the stdio core.

This package wraps the existing stdio engine (``load_docs`` / ``build_server``)
without modifying it, serving one git-sourced owner over MCP Streamable HTTP at
``/{owner}/mcp``. Multi-owner routing, auth, TTL refresh, and Docker packaging
arrive in later tasks.
"""

from __future__ import annotations

from .app import create_app
from .config import GatewayConfig

__all__ = ["GatewayConfig", "create_app"]
