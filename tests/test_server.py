"""Tests for okf_mcp_server.server (frontmatter-driven loader + MCP server)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import mcp.types as mcp_types
import pytest
from pydantic import AnyUrl

from okf_mcp_server.config import ServerConfig
from okf_mcp_server.server import (
    ParsedDoc,
    _first_paragraph,
    build_server,
    extract_id,
    load_docs,
    slugify_type,
)


def _write(dir: Path, name: str, body: str) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _config(owner: str, roots: tuple[Path, ...]) -> ServerConfig:
    return ServerConfig(owner=owner, roots=roots)


def _front(meta_block: str, body: str = "Body para.\n") -> str:
    return f"---\n{meta_block}---\n\n{body}"


def test_slugify_type_replaces_non_alphanumeric_with_dash() -> None:
    assert slugify_type("Architecture Decision") == "architecture-decision"


def test_slugify_type_collapses_runs_of_dashes() -> None:
    assert slugify_type("Strategy  -- doc") == "strategy-doc"


def test_slugify_type_trims_leading_trailing_dashes() -> None:
    assert slugify_type("--Strategy--doc--") == "strategy-doc"


def test_slugify_type_lowercases() -> None:
    assert slugify_type("ADR") == "adr"


def test_slugify_type_returns_empty_for_empty_input() -> None:
    assert slugify_type("") == ""


def test_slugify_type_returns_empty_for_pure_punctuation() -> None:
    assert slugify_type("---") == ""


def test_extract_id_prefers_frontmatter_id() -> None:
    p = Path("backlog/docs/doc-99 - Whatever.md")
    assert extract_id({"id": "custom-id"}, p) == "custom-id"


def test_extract_id_falls_back_to_first_whitespace_token() -> None:
    p = Path("backlog/docs/doc-1 - Project overview.md")
    assert extract_id({}, p) == "doc-1"


def test_extract_id_uses_full_stem_when_no_whitespace() -> None:
    p = Path("design/c8-saas-simplified-brainstorm.md")
    assert extract_id({}, p) == "c8-saas-simplified-brainstorm"


def test_extract_id_treats_blank_frontmatter_id_as_absent() -> None:
    p = Path("backlog/docs/doc-2 - Title.md")
    assert extract_id({"id": "   "}, p) == "doc-2"


def test_extract_id_coerces_non_string_frontmatter_id() -> None:
    p = Path("backlog/docs/doc-99 - whatever.md")
    assert extract_id({"id": 42}, p) == "42"


def test_first_paragraph_skips_headings() -> None:
    body = "# Heading 1\n\n## Heading 2\n\nReal paragraph here.\n\nLater stuff."
    assert _first_paragraph(body) == "Real paragraph here."


def test_first_paragraph_truncates_to_limit() -> None:
    body = "x" * 800
    assert len(_first_paragraph(body, limit=100)) == 100


def test_first_paragraph_returns_empty_when_only_headings() -> None:
    assert _first_paragraph("# H1\n\n## H2\n") == ""


def test_parsed_doc_uri_uses_type_slug() -> None:
    doc = ParsedDoc(
        owner="stacks",
        type="Architecture Decision",
        type_slug="architecture-decision",
        id="decision-2",
        title="Knowledge Mesh",
        description="d",
        content="body",
    )
    assert doc.uri == "knowledge://stacks/architecture-decision/decision-2"


def test_parsed_doc_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    doc = ParsedDoc(
        owner="stacks",
        type="Doc",
        type_slug="doc",
        id="doc-1",
        title="t",
        description="d",
        content="c",
    )
    with pytest.raises(FrozenInstanceError):
        doc.id = "other"  # type: ignore[misc]


def test_load_docs_filters_out_files_without_export_true(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    _write(docs_dir, "yes.md", _front("type: Doc\nexport: true\n"))
    _write(docs_dir, "no.md", _front("type: Doc\n"))
    _write(docs_dir, "false.md", _front("type: Doc\nexport: false\n"))
    docs = load_docs(_config("stacks", (docs_dir,)))
    assert [d.id for d in docs] == ["yes"]


def test_load_docs_filters_out_files_without_type(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    _write(docs_dir, "ok.md", _front("type: Doc\nexport: true\n"))
    _write(docs_dir, "no-type.md", _front("export: true\n"))
    _write(docs_dir, "blank-type.md", _front("type: '   '\nexport: true\n"))
    docs = load_docs(_config("stacks", (docs_dir,)))
    assert [d.id for d in docs] == ["ok"]


def test_load_docs_emits_uri_with_slugified_type(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    _write(
        docs_dir,
        "decision-2 - Mesh.md",
        _front("id: decision-2\ntype: Architecture Decision\nexport: true\n"),
    )
    docs = load_docs(_config("stacks", (docs_dir,)))
    assert len(docs) == 1
    assert docs[0].type == "Architecture Decision"
    assert docs[0].type_slug == "architecture-decision"
    assert docs[0].uri == "knowledge://stacks/architecture-decision/decision-2"


def test_load_docs_recurses_into_subdirs(tmp_path: Path) -> None:
    root = tmp_path / "design"
    _write(root, "a.md", _front("type: Design\nexport: true\n"))
    _write(root / "sub", "b.md", _front("type: Design\nexport: true\n"))
    docs = load_docs(_config("stacks", (root,)))
    assert sorted(d.id for d in docs) == ["a", "b"]


def test_load_docs_description_prefers_frontmatter(tmp_path: Path) -> None:
    docs_dir = tmp_path / "d"
    _write(
        docs_dir,
        "doc-1 - X.md",
        _front(
            "id: doc-1\ntitle: X\ntype: Doc\nexport: true\ndescription: explicit desc\n"
        ),
    )
    docs = load_docs(_config("stacks", (docs_dir,)))
    assert docs[0].description == "explicit desc"


def test_load_docs_description_falls_back_to_first_paragraph(tmp_path: Path) -> None:
    docs_dir = tmp_path / "d"
    _write(
        docs_dir,
        "doc-1 - X.md",
        _front(
            "id: doc-1\ntitle: X\ntype: Doc\nexport: true\n",
            "# Heading\n\nFallback para.\n",
        ),
    )
    docs = load_docs(_config("stacks", (docs_dir,)))
    assert docs[0].description == "Fallback para."


def test_load_docs_title_falls_back_to_stem(tmp_path: Path) -> None:
    docs_dir = tmp_path / "d"
    _write(docs_dir, "doc-1 - Stem-name.md", _front("type: Doc\nexport: true\n"))
    docs = load_docs(_config("stacks", (docs_dir,)))
    assert docs[0].title == "doc-1 - Stem-name"


def test_load_docs_returns_empty_when_no_files_match(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert load_docs(_config("stacks", (empty,))) == []


def test_load_docs_design_id_uses_full_stem(tmp_path: Path) -> None:
    design = tmp_path / "design"
    _write(
        design,
        "c8-saas-simplified-brainstorm.md",
        _front("type: Brainstorm\nexport: true\n"),
    )
    docs = load_docs(_config("stacks", (design,)))
    assert docs[0].id == "c8-saas-simplified-brainstorm"


def test_load_docs_strips_frontmatter_from_content(tmp_path: Path) -> None:
    docs_dir = tmp_path / "d"
    _write(
        docs_dir,
        "doc-1 - X.md",
        _front("id: doc-1\ntitle: X\ntype: Doc\nexport: true\n", "Body line.\n"),
    )
    docs = load_docs(_config("stacks", (docs_dir,)))
    assert "---" not in docs[0].content
    assert "Body line." in docs[0].content


def _docs_sample() -> list[ParsedDoc]:
    return [
        ParsedDoc(
            owner="stacks",
            type="Reference doc",
            type_slug="reference-doc",
            id="doc-1",
            title="Doc One",
            description="d1",
            content="BODY-DOC-1",
        ),
        ParsedDoc(
            owner="stacks",
            type="Architecture Decision",
            type_slug="architecture-decision",
            id="decision-2",
            title="Decision Two",
            description="d2",
            content="BODY-DEC-2",
        ),
    ]


def _call_handler(server: Any, request_cls: Any, params: object) -> Any:
    handler = server.request_handlers[request_cls]
    request = request_cls(
        method=request_cls.model_fields["method"].default,
        params=params,
    )
    return asyncio.run(handler(request))


def test_build_server_lists_resources_with_owner_typeslug_id_uri() -> None:
    server = build_server(_docs_sample())
    result = _call_handler(server, mcp_types.ListResourcesRequest, None)
    uris = [str(r.uri) for r in result.root.resources]
    assert uris == [
        "knowledge://stacks/reference-doc/doc-1",
        "knowledge://stacks/architecture-decision/decision-2",
    ]


def test_build_server_read_resource_matches_on_type_slug_and_id() -> None:
    server = build_server(_docs_sample())
    uri = AnyUrl("knowledge://stacks/architecture-decision/decision-2")
    result = _call_handler(
        server,
        mcp_types.ReadResourceRequest,
        mcp_types.ReadResourceRequestParams(uri=uri),
    )
    assert result.root.contents[0].text == "BODY-DEC-2"


def test_build_server_read_resource_distinguishes_same_id_different_type() -> None:
    docs = [
        ParsedDoc(
            owner="stacks",
            type="Doc",
            type_slug="doc",
            id="alpha",
            title="t",
            description="d",
            content="DOC-BODY",
        ),
        ParsedDoc(
            owner="stacks",
            type="Decision",
            type_slug="decision",
            id="alpha",
            title="t",
            description="d",
            content="DEC-BODY",
        ),
    ]
    server = build_server(docs)
    uri = AnyUrl("knowledge://stacks/decision/alpha")
    result = _call_handler(
        server,
        mcp_types.ReadResourceRequest,
        mcp_types.ReadResourceRequestParams(uri=uri),
    )
    assert result.root.contents[0].text == "DEC-BODY"


def test_build_server_read_resource_unknown_uri_raises() -> None:
    server = build_server(_docs_sample())
    uri = AnyUrl("knowledge://stacks/doc/missing")
    with pytest.raises(ValueError, match="unknown resource"):
        _call_handler(
            server,
            mcp_types.ReadResourceRequest,
            mcp_types.ReadResourceRequestParams(uri=uri),
        )


def test_run_exported() -> None:
    import okf_mcp_server

    assert callable(okf_mcp_server.run)
    assert "run" in okf_mcp_server.__all__


def test_load_docs_uses_owner_override_in_uri(tmp_path: Path) -> None:
    """Owner override flows end-to-end into the resource URI."""
    import subprocess

    from okf_mcp_server.config import resolve_config

    repo = tmp_path / "workspace"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    design = repo / "design"
    _write(design, "decision-2 - X.md", _front("type: Doc\nexport: true\n"))

    config = resolve_config(flag_owner="stacks", env={}, cwd=repo)
    docs = load_docs(config)
    assert len(docs) == 1
    assert docs[0].uri == "knowledge://stacks/doc/decision-2"
