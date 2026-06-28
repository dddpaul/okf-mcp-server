"""CLI entry point for okf-mcp-lint."""

from __future__ import annotations

import argparse
import sys

from okf_mcp_server.linter import run_lint


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="okf-mcp-lint",
        description=(
            "Lint OKF-style frontmatter for id uniqueness and export validity. "
            "Exits non-zero on errors; warnings do not affect exit code."
        ),
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
    sys.exit(run_lint(roots=args.roots, owner=args.owner))


if __name__ == "__main__":
    main()
