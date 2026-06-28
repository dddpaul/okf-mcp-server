"""Smoke test — load the sample git-init'd repo via resolve_config + load_docs."""

from __future__ import annotations

from pathlib import Path

from okf_mcp_server.config import resolve_config
from okf_mcp_server.server import load_docs


def test_fixture_loads_three_docs_with_expected_uris(sample_repo: Path) -> None:
    config = resolve_config(env={}, cwd=sample_repo)
    docs = load_docs(config)

    assert config.owner == "sample"
    assert len(docs) == 3
    uris = sorted(d.uri for d in docs)
    assert uris == [
        "knowledge://sample/architecture-decision/decision-1",
        "knowledge://sample/design/sample-design",
        "knowledge://sample/reference-doc/doc-1",
    ]
    assert all(d.content.strip() for d in docs)
