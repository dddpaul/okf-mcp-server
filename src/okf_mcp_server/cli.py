"""CLI entry point for okf-mcp-server."""

from __future__ import annotations

import argparse

from okf_mcp_server import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="okf-mcp-server",
        description="Serve OKF-style frontmatter docs as MCP resources over stdio.",
    )
    parser.add_argument(
        "--roots",
        default=None,
        help=(
            "Comma-separated list of root directories to scan. "
            "Resolved relative to the git toplevel. "
            "Overrides the OKF_MCP_ROOTS env var (colon-separated). "
            "Default: design/, backlog/docs/, backlog/decisions/."
        ),
    )
    parser.add_argument(
        "--owner",
        default=None,
        help=(
            "Owner segment for resource URIs. "
            "Overrides the OKF_MCP_OWNER env var. "
            "Default: basename of the git toplevel, falling back to basename of cwd."
        ),
    )
    args = parser.parse_args()
    run(roots=args.roots, owner=args.owner)


if __name__ == "__main__":
    main()
