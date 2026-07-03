"""Console entry point for okf-mcp-gateway (single-owner slice, US-001).

Resolves one owner from the environment, shallow-clones its repo, and serves it
over MCP Streamable HTTP with uvicorn. The default bind is ``0.0.0.0:8080`` to
match the container deployment target defined in the PRD.
"""

from __future__ import annotations

import os

import uvicorn

from .app import create_app
from .config import GatewayConfig

ENV_HOST = "OKF_GATEWAY_HOST"
ENV_PORT = "OKF_GATEWAY_PORT"
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 — container bind; PRD default 0.0.0.0:8080
DEFAULT_PORT = 8080


def main() -> None:
    """Build the gateway app from the environment and run it under uvicorn."""
    config = GatewayConfig.from_env()
    app = create_app(config)
    host = os.environ.get(ENV_HOST, "").strip() or DEFAULT_HOST
    port = int(os.environ.get(ENV_PORT, "").strip() or DEFAULT_PORT)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
