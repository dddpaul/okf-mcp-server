"""Tests for okf_mcp_server.server (frontmatter-driven loader + MCP server)."""

from __future__ import annotations

import asyncio
import hashlib
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


def test_content_hash_is_deterministic_sha256_over_served_content() -> None:
    body = "IDENTICAL BODY BYTES"
    doc = ParsedDoc(
        owner="stacks",
        type="Reference Doc",
        type_slug="reference-doc",
        id="a",
        title="ta",
        description="da",
        content=body,
    )
    # Two docs with byte-identical content but otherwise different metadata hash
    # identically: the hash is a pure content identity (not resource identity),
    # which is exactly what no-op-wake detection needs.
    twin = ParsedDoc(
        owner="other",
        type="Architecture Decision",
        type_slug="architecture-decision",
        id="b",
        title="tb",
        description="db",
        content=body,
    )
    changed = ParsedDoc(
        owner="stacks",
        type="Reference Doc",
        type_slug="reference-doc",
        id="a",
        title="ta",
        description="da",
        content=body + " CHANGED",
    )
    expected = "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert doc.content_hash == expected
    assert doc.content_hash == twin.content_hash  # identical content -> same hash
    assert doc.content_hash != changed.content_hash  # changed bytes -> new hash


def test_list_resources_exposes_content_hash_in_meta() -> None:
    docs = _docs_sample()
    server = build_server(docs)
    result = _call_handler(server, mcp_types.ListResourcesRequest, None)
    by_uri = {str(r.uri): r for r in result.root.resources}
    for d in docs:
        meta = by_uri[d.uri].meta
        assert meta is not None
        assert meta["content_hash"] == d.content_hash
        assert meta["content_hash"].startswith("sha256:")


def test_read_resource_exposes_content_hash_matching_list_and_keeps_body() -> None:
    docs = _docs_sample()
    server = build_server(docs)
    target = docs[1]  # decision-2, content "BODY-DEC-2"
    result = _call_handler(
        server,
        mcp_types.ReadResourceRequest,
        mcp_types.ReadResourceRequestParams(uri=AnyUrl(target.uri)),
    )
    content = result.root.contents[0]
    assert content.text == target.content  # served body is unchanged
    assert content.meta is not None
    assert content.meta["content_hash"] == target.content_hash


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


def test_load_docs_dedups_symlinked_doc_to_unique_uri(tmp_path: Path) -> None:
    """Gateway whole-root scan must not list a symlinked doc twice.

    Reproduces the live ``stacks`` scenario: the checkout root holds the
    canonical ``backlog/docs/doc-1*.md`` plus a repo-root ``README.md`` symlink
    into it (the single-source pattern GitHub requires). Scanning the whole
    root — as ``owner_cache`` does with ``roots=(checkout,)`` — reaches both,
    yet ``resources/list`` must expose exactly one ``knowledge://`` URI.
    """
    import os

    import frontmatter

    repo = tmp_path / "repo"
    canonical = _write(
        repo / "backlog" / "docs",
        "doc-1 - Project overview.md",
        _front(
            "id: doc-1\ntitle: Project overview\ntype: readme\nexport: true\n",
            "Project overview body.\n",
        ),
    )
    try:
        os.symlink(canonical, repo / "README.md")
    except (OSError, NotImplementedError):  # pragma: no cover - platform guard
        pytest.skip("filesystem does not support symlinks")

    docs = load_docs(_config("stacks", (repo,)))

    uris = [d.uri for d in docs]
    assert uris.count("knowledge://stacks/readme/doc-1") == 1
    assert len(uris) == len(set(uris))  # every URI is unique

    (only,) = [d for d in docs if d.uri == "knowledge://stacks/readme/doc-1"]
    assert only.content != ""
    assert only.content == frontmatter.load(canonical).content


def test_load_docs_records_path_relative_to_the_scan_root(tmp_path: Path) -> None:
    """``path`` locates a doc within the root it was scanned under, not on disk.

    The gateway scans an owner's checkout as a single root, so this is exactly the
    repo-relative path it surfaces on ``GET /status?artifacts=true`` — an absolute
    checkout path would leak the gateway's filesystem layout and be unusable
    remotely.
    """
    root = tmp_path / "checkout"
    _write(root / "docs", "top.md", _front("type: Doc\nexport: true\nid: a\n"))
    _write(
        root / "design" / "adr",
        "nested.md",
        _front("type: Decision\nexport: true\nid: b\n"),
    )

    docs = load_docs(_config("stacks", (root,)))

    by_id = {d.id: d for d in docs}
    assert by_id["a"].path == "docs/top.md"
    assert by_id["b"].path == "design/adr/nested.md"  # slash-separated, any depth
    # Relative to the root: neither the absolute prefix nor a leading slash leaks.
    for doc in docs:
        assert not Path(doc.path).is_absolute()
        assert str(tmp_path) not in doc.path


def test_parsed_doc_size_is_the_length_of_the_served_content() -> None:
    doc = ParsedDoc(
        owner="stacks",
        type="Doc",
        type_slug="doc",
        id="a",
        title="t",
        description="d",
        content="BODY BYTES",
    )
    assert doc.size == len(doc.content) == 10


def test_load_docs_size_measures_the_body_not_the_file(tmp_path: Path) -> None:
    """``size`` covers the served content only — frontmatter is already stripped."""
    root = tmp_path / "checkout"
    path = _write(root, "doc.md", _front("type: Doc\nexport: true\nid: a\n"))

    (doc,) = load_docs(_config("stacks", (root,)))

    assert doc.size == len(doc.content)
    assert doc.size < len(path.read_text(encoding="utf-8"))  # frontmatter excluded


def test_parsed_doc_path_defaults_to_empty_so_the_field_is_additive() -> None:
    """A doc built without a root still constructs; ``path`` is opt-in metadata."""
    doc = ParsedDoc(
        owner="stacks",
        type="Doc",
        type_slug="doc",
        id="a",
        title="t",
        description="d",
        content="c",
    )
    assert doc.path == ""
