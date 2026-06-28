"""Read-only contract — assert build_server exposes no tools, only resources.

decision-2 (Knowledge Mesh foundation, 2026-06-23 amendment) locks the MCP
surface to read-only resources. This test fails if a future contributor wires
``@server.call_tool()`` or ``@server.list_tools()`` into ``build_server``.
"""

from __future__ import annotations

from pathlib import Path

import mcp.types as mcp_types

from okf_mcp_server.config import resolve_config
from okf_mcp_server.server import build_server, load_docs


def test_build_server_registers_no_tool_handlers(sample_repo: Path) -> None:
    docs = load_docs(resolve_config(env={}, cwd=sample_repo))
    server = build_server(docs)

    assert mcp_types.CallToolRequest not in server.request_handlers, (
        "Read-only contract violated: build_server registered a @call_tool handler"
    )
    assert mcp_types.ListToolsRequest not in server.request_handlers, (
        "Read-only contract violated: build_server registered a @list_tools handler"
    )


def test_build_server_registers_resource_handlers(sample_repo: Path) -> None:
    docs = load_docs(resolve_config(env={}, cwd=sample_repo))
    server = build_server(docs)

    assert mcp_types.ListResourcesRequest in server.request_handlers
    assert mcp_types.ReadResourceRequest in server.request_handlers
