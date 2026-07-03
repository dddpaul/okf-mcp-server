"""Process-level configuration for the multi-owner gateway (US-002).

Owners themselves are declared in ``servers.yaml`` (see :mod:`.registry`); this
module resolves only where that file lives and where checkouts are cached, from
environment variables.

Environment variables:
    ``OKF_GATEWAY_SERVERS``   Path to ``servers.yaml`` (default: ``servers.yaml``).
    ``OKF_GATEWAY_CACHE_DIR`` Cache directory for checkouts (default: XDG cache).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_SERVERS = "OKF_GATEWAY_SERVERS"
ENV_CACHE_DIR = "OKF_GATEWAY_CACHE_DIR"

DEFAULT_SERVERS = "servers.yaml"


def _default_cache_dir(env: dict[str, str]) -> Path:
    xdg = env.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "okf-mcp-gateway"


@dataclass(frozen=True)
class GatewayConfig:
    """Resolved process configuration for the gateway.

    Attributes:
        servers_path: Path to the ``servers.yaml`` registry to load at startup.
        cache_dir: Directory under which per-owner checkouts are written.
    """

    servers_path: Path
    cache_dir: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> GatewayConfig:
        """Resolve configuration from environment variables.

        Args:
            env: Environment mapping; defaults to ``os.environ``.

        Returns:
            A resolved ``GatewayConfig``.
        """
        environ = dict(os.environ) if env is None else env
        servers_raw = environ.get(ENV_SERVERS, "").strip()
        servers_path = Path(servers_raw) if servers_raw else Path(DEFAULT_SERVERS)
        cache_raw = environ.get(ENV_CACHE_DIR, "").strip()
        cache_dir = Path(cache_raw) if cache_raw else _default_cache_dir(environ)
        return cls(servers_path=servers_path, cache_dir=cache_dir)


__all__ = [
    "ENV_CACHE_DIR",
    "ENV_SERVERS",
    "GatewayConfig",
]
