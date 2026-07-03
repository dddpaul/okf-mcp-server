"""Minimal gateway configuration for the single-owner vertical slice (US-001).

The full multi-owner registry (``servers.yaml``) arrives in a later task; this
module resolves exactly one owner from environment variables so the thin slice
can serve a single git-sourced owner end to end.

Environment variables:
    ``OKF_GATEWAY_OWNER``    Owner segment used in resource URIs and the route.
    ``OKF_GATEWAY_GIT_URL``  Git URL to shallow-clone the owner's docs from.
    ``OKF_GATEWAY_GIT_REF``  Branch or tag to check out (default: ``main``).
    ``OKF_GATEWAY_CACHE_DIR``Cache directory for checkouts (default: XDG cache).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_OWNER = "OKF_GATEWAY_OWNER"
ENV_GIT_URL = "OKF_GATEWAY_GIT_URL"
ENV_GIT_REF = "OKF_GATEWAY_GIT_REF"
ENV_CACHE_DIR = "OKF_GATEWAY_CACHE_DIR"

DEFAULT_REF = "main"


def _default_cache_dir(env: dict[str, str]) -> Path:
    xdg = env.get("XDG_CACHE_HOME", "").strip()
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "okf-mcp-gateway"


@dataclass(frozen=True)
class GatewayConfig:
    """Resolved configuration for a single owner served by the gateway.

    Attributes:
        owner: Owner segment used in resource URIs and the ``/{owner}/mcp`` route.
        git_url: Git URL cloned to source the owner's docs.
        ref: Branch or tag checked out from ``git_url``.
        cache_dir: Directory under which per-owner checkouts are written.
    """

    owner: str
    git_url: str
    ref: str
    cache_dir: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> GatewayConfig:
        """Resolve configuration from environment variables.

        Args:
            env: Environment mapping; defaults to ``os.environ``.

        Returns:
            A validated ``GatewayConfig``.

        Raises:
            ValueError: If ``OKF_GATEWAY_OWNER`` or ``OKF_GATEWAY_GIT_URL`` is
                missing or blank.
        """
        environ = dict(os.environ) if env is None else env
        owner = environ.get(ENV_OWNER, "").strip()
        if not owner:
            raise ValueError(f"{ENV_OWNER} is required")
        git_url = environ.get(ENV_GIT_URL, "").strip()
        if not git_url:
            raise ValueError(f"{ENV_GIT_URL} is required")
        ref = environ.get(ENV_GIT_REF, "").strip() or DEFAULT_REF
        cache_raw = environ.get(ENV_CACHE_DIR, "").strip()
        cache_dir = Path(cache_raw) if cache_raw else _default_cache_dir(environ)
        return cls(owner=owner, git_url=git_url, ref=ref, cache_dir=cache_dir)


__all__ = [
    "ENV_CACHE_DIR",
    "ENV_GIT_REF",
    "ENV_GIT_URL",
    "ENV_OWNER",
    "GatewayConfig",
]
