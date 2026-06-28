"""okf-mcp-server — frontmatter-driven OKF source server over MCP/stdio."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .config import resolve_config
from .linter import run_lint
from .server import build_server, load_docs, serve_stdio


def run(
    roots: str | None = None,
    owner: str | None = None,
    base_dir: Path | None = None,
) -> None:
    config = resolve_config(flag_roots=roots, flag_owner=owner, base_dir=base_dir)
    docs = load_docs(config)
    print(
        f"okf-mcp-server: loaded {len(docs)} docs from owner={config.owner!r} "
        f"across {len(config.roots)} root(s)",
        file=sys.stderr,
    )
    server = build_server(docs)
    asyncio.run(serve_stdio(server))


__all__ = ["run", "run_lint"]
