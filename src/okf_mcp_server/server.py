"""Frontmatter-driven OKF document loader and MCP server builder.

A file is exported when its frontmatter has both ``export: true`` and a
non-empty ``type``. The free-form ``type`` is slugified into the URI segment
(``"Architecture Decision"`` -> ``architecture-decision``); the contract is
held by the stable ``id``, not by the slug.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import frontmatter
import mcp.server.stdio
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.types import Resource

from .config import ServerConfig

DESCRIPTION_LIMIT = 500

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ParsedDoc:
    owner: str
    type: str
    type_slug: str
    id: str
    title: str
    description: str
    content: str

    @property
    def uri(self) -> str:
        return f"knowledge://{self.owner}/{self.type_slug}/{self.id}"

    @property
    def content_hash(self) -> str:
        """Return a deterministic ``sha256:<hex>`` digest of the served content.

        The hash is taken over exactly the bytes ``read_resource`` returns (the
        UTF-8-encoded frontmatter body), so it is a stable identity of the served
        representation: byte-identical content always yields the same hash,
        regardless of which commit produced it. This lets a downstream consumer
        detect a no-op wake — the owner's commit moved, but this specific
        artifact is unchanged — independently of the owner-level ``served_commit``
        provenance signal. The ``sha256:`` prefix names the algorithm so the
        digest is self-describing.
        """
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


def slugify_type(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-")


def _first_paragraph(body: str, limit: int = DESCRIPTION_LIMIT) -> str:
    for chunk in body.strip().split("\n\n"):
        chunk = chunk.strip()
        if chunk and not chunk.startswith("#"):
            return chunk.split("\n", 1)[0].strip()[:limit]
    return ""


def extract_id(meta: dict[str, Any], path: Path) -> str:
    fid = meta.get("id")
    if fid is not None and str(fid).strip():
        return str(fid).strip()
    stem = path.stem
    if " " in stem:
        return stem.split(" ", 1)[0]
    return stem


def _iter_markdown_files(root: Path) -> list[Path]:
    # Skip symlinks: a repo-root ``README.md`` aliasing ``backlog/docs/`` (the
    # single-source pattern GitHub requires) would otherwise be indexed on top
    # of its canonical target. We parse the real file, not the alias.
    return sorted(p for p in root.rglob("*.md") if p.is_file() and not p.is_symlink())


def _build_doc(owner: str, path: Path) -> ParsedDoc | None:
    fm = frontmatter.load(path)
    if fm.metadata.get("export") is not True:
        return None
    raw_type = str(fm.metadata.get("type") or "").strip()
    if not raw_type:
        return None
    type_slug = slugify_type(raw_type)
    if not type_slug:
        return None
    doc_id = extract_id(fm.metadata, path)
    title = str(fm.metadata.get("title") or path.stem)
    desc = fm.metadata.get("description") or _first_paragraph(fm.content)
    return ParsedDoc(
        owner=owner,
        type=raw_type,
        type_slug=type_slug,
        id=doc_id,
        title=title,
        description=str(desc),
        content=fm.content,
    )


def load_docs(config: ServerConfig) -> list[ParsedDoc]:
    docs: list[ParsedDoc] = []
    # MCP resource URIs must be unique. Dedup by ``ParsedDoc.uri`` (first
    # occurrence wins) as a structural backstop against any filesystem aliasing
    # — symlinks, overlapping roots, or a duplicated ``id`` — regardless of how
    # the same knowledge:// URI is reached twice.
    seen: set[str] = set()
    for root in config.roots:
        for path in _iter_markdown_files(root):
            doc = _build_doc(config.owner, path)
            if doc is not None and doc.uri not in seen:
                seen.add(doc.uri)
                docs.append(doc)
    return docs


def build_server(docs: list[ParsedDoc]) -> Server:
    server: Server = Server("okf-mcp-server")

    @server.list_resources()
    async def _list() -> list[Resource]:
        # content_hash rides in each resource's ``_meta`` so a consumer can pin a
        # content-identity dependency from the listing alone, without a read.
        return [
            Resource(
                uri=d.uri,  # type: ignore[arg-type]
                name=d.title,
                description=d.description,
                mimeType="text/markdown",
                _meta={"content_hash": d.content_hash},
            )
            for d in docs
        ]

    @server.read_resource()
    async def _read(uri: Any) -> Iterable[ReadResourceContents]:
        parsed = urlparse(str(uri))
        parts = parsed.path.strip("/").split("/", 1)
        if parsed.scheme != "knowledge" or len(parts) != 2:
            raise ValueError(f"invalid resource uri: {uri}")
        type_slug, doc_id = parts
        for d in docs:
            if d.type_slug == type_slug and d.id == doc_id:
                # Return ReadResourceContents (not a bare str) so content_hash
                # travels in the result's ``_meta`` and the served bytes carry
                # their own content-identity signal.
                return [
                    ReadResourceContents(
                        content=d.content,
                        mime_type="text/markdown",
                        meta={"content_hash": d.content_hash},
                    )
                ]
        raise ValueError(f"unknown resource: {uri}")

    return server


async def serve_stdio(server: Server) -> None:
    async with mcp.server.stdio.stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


__all__ = [
    "ParsedDoc",
    "build_server",
    "extract_id",
    "load_docs",
    "serve_stdio",
    "slugify_type",
]
