"""Resolve owner and scan roots for okf-mcp-server.

Owner resolution (first non-empty wins): ``--owner`` flag, ``OKF_MCP_OWNER``
env var, basename of the git toplevel, basename of cwd (with a warning if cwd
is not in a git repo). Scan roots come from --roots flag, then
OKF_MCP_ROOTS env var, then a built-in default — resolved relative to the
git toplevel, with missing roots skipped (warning, no abort).

When ``base_dir`` is supplied, it replaces the process cwd as the starting
point for git toplevel discovery and root resolution; the owner chain's
process-cwd fallback (fourth link) is unchanged. This lets a shim physically
located inside the canonical repo serve content from there even when the host
process starts in an unrelated consumer repo.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOTS: tuple[str, ...] = ("design/", "backlog/docs/", "backlog/decisions/")
ENV_ROOTS = "OKF_MCP_ROOTS"
ENV_OWNER = "OKF_MCP_OWNER"


@dataclass(frozen=True)
class ServerConfig:
    owner: str
    roots: tuple[Path, ...]


def _git_toplevel(cwd: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    output = result.stdout.strip()
    if not output:
        return None
    return Path(output)


def _split_roots(value: str, sep: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(sep) if item.strip())


def _resolve_roots(
    flag_roots: str | None,
    env: dict[str, str],
    base: Path,
) -> tuple[Path, ...]:
    if flag_roots and flag_roots.strip():
        raw = _split_roots(flag_roots, ",")
    elif env.get(ENV_ROOTS, "").strip():
        raw = _split_roots(env[ENV_ROOTS], ":")
    else:
        raw = DEFAULT_ROOTS

    resolved: list[Path] = []
    for item in raw:
        candidate = (base / item).resolve()
        if not candidate.exists():
            print(
                f"okf-mcp-server: root {item!r} not found at {candidate}; skipping",
                file=sys.stderr,
            )
            continue
        resolved.append(candidate)
    return tuple(resolved)


def _resolve_owner(
    flag_owner: str | None,
    env: dict[str, str],
    toplevel: Path | None,
    cwd: Path,
) -> str:
    if flag_owner and flag_owner.strip():
        return flag_owner.strip()
    env_owner = env.get(ENV_OWNER, "").strip()
    if env_owner:
        return env_owner
    if toplevel is not None:
        return toplevel.name
    owner = cwd.name
    print(
        f"okf-mcp-server: not a git repo; "
        f"falling back to owner={owner!r} (basename of cwd)",
        file=sys.stderr,
    )
    return owner


def resolve_config(
    flag_roots: str | None = None,
    flag_owner: str | None = None,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    base_dir: Path | None = None,
) -> ServerConfig:
    cwd = (cwd or Path.cwd()).resolve()
    start = base_dir.resolve() if base_dir is not None else cwd
    effective_env = dict(os.environ) if env is None else env

    toplevel = _git_toplevel(start)
    root_base = toplevel if toplevel is not None else start

    owner = _resolve_owner(flag_owner, effective_env, toplevel, cwd)
    roots = _resolve_roots(flag_roots, effective_env, root_base)
    return ServerConfig(owner=owner, roots=roots)


__all__ = [
    "DEFAULT_ROOTS",
    "ENV_OWNER",
    "ENV_ROOTS",
    "ServerConfig",
    "resolve_config",
]
