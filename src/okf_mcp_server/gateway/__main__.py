"""Console entry point for okf-mcp-gateway (multi-owner registry, US-002/US-004).

Loads the ``servers.yaml`` registry, builds the multi-owner app (which
eager-clones registered owners in the background), and serves it over MCP
Streamable HTTP with uvicorn. A missing north bearer token (``OKF_GATEWAY_TOKEN``)
or a missing/malformed registry fails fast with a clear message before uvicorn
starts — the gateway refuses to run without consumer auth. The default bind is
``0.0.0.0:8080`` to match the container deployment target defined in the PRD.
"""

from __future__ import annotations

import os
import sys

import uvicorn

from .app import create_app
from .config import GatewayConfig
from .registry import RegistryError, load_registry

ENV_HOST = "OKF_GATEWAY_HOST"
ENV_PORT = "OKF_GATEWAY_PORT"
ENV_TOKEN = "OKF_GATEWAY_TOKEN"
DEFAULT_HOST = "0.0.0.0"  # noqa: S104 — container bind; PRD default 0.0.0.0:8080
DEFAULT_PORT = 8080


def main() -> None:
    """Load config, build the gateway app with north auth, and run it under uvicorn.

    Raises:
        SystemExit: If the north bearer token is unset, or ``servers.yaml`` is
            missing or malformed (exit code 1).
    """
    config = GatewayConfig.from_env()
    token = os.environ.get(ENV_TOKEN, "").strip()
    if not token:
        print(
            f"okf-mcp-gateway: {ENV_TOKEN} is not set; refusing to start without "
            f"consumer auth (set it to the shared north bearer token)",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        registry = load_registry(config.servers_path)
    except RegistryError as exc:
        print(f"okf-mcp-gateway: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    app = create_app(registry, config.cache_dir, auth_token=token)
    host = os.environ.get(ENV_HOST, "").strip() or DEFAULT_HOST
    port = int(os.environ.get(ENV_PORT, "").strip() or DEFAULT_PORT)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
