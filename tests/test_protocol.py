"""Protocol test — spawn CLI as a subprocess in the sample repo, verify MCP."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_URIS = {
    "knowledge://sample/reference-doc/doc-1",
    "knowledge://sample/architecture-decision/decision-1",
    "knowledge://sample/design/sample-design",
}


async def _exercise_protocol(repo: Path) -> None:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "okf_mcp_server.cli"],
        cwd=str(repo),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            listed = await session.list_resources()
            uris = {str(r.uri) for r in listed.resources}
            assert uris == EXPECTED_URIS

            for resource in listed.resources:
                result = await session.read_resource(resource.uri)
                assert result.contents, f"no contents for {resource.uri}"
                payload = result.contents[0]
                text = getattr(payload, "text", None) or getattr(payload, "blob", None)
                assert text and text.strip(), f"empty body for {resource.uri}"


def test_protocol_lists_three_resources_and_reads_each(sample_repo: Path) -> None:
    asyncio.run(_exercise_protocol(sample_repo))
