"""Frontmatter linter for the OKF source format.

Three invariants are checked over the same roots the server scans:

1. **ERROR** — duplicate ``id`` within owner (the consumer contract is the
   stable ``id``; collisions silently shadow one document).
2. **ERROR** — ``export: true`` with missing or empty ``type`` (the strict
   export gate requires both; opted-in-but-typeless files would be silently
   dropped by the server).
3. **WARNING** — two distinct ``type`` values that slugify to the same
   URI segment (consumers see one slug for two unrelated docs).

Derivation of ``id`` and ``type-slug`` is imported from
:mod:`okf_mcp_server.server`; the linter never reimplements them so its
verdicts cannot drift from the server's loading behaviour.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from .config import ServerConfig, resolve_config
from .server import _iter_markdown_files, extract_id, slugify_type

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class LintFinding:
    severity: str
    message: str


@dataclass(frozen=True)
class LintResult:
    findings: tuple[LintFinding, ...] = field(default_factory=tuple)

    @property
    def errors(self) -> tuple[LintFinding, ...]:
        return tuple(f for f in self.findings if f.severity == ERROR)

    @property
    def warnings(self) -> tuple[LintFinding, ...]:
        return tuple(f for f in self.findings if f.severity == WARNING)

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


def lint(config: ServerConfig) -> LintResult:
    findings: list[LintFinding] = []
    id_to_paths: dict[str, list[Path]] = {}
    slug_to_types: dict[str, set[str]] = {}

    for root in config.roots:
        for path in _iter_markdown_files(root):
            fm = frontmatter.load(path)
            if fm.metadata.get("export") is not True:
                continue
            raw_type = str(fm.metadata.get("type") or "").strip()
            if not raw_type:
                findings.append(
                    LintFinding(
                        severity=ERROR,
                        message=(
                            f"{path}: export: true requires a non-empty `type`"
                        ),
                    )
                )
                continue
            doc_id = extract_id(fm.metadata, path)
            id_to_paths.setdefault(doc_id, []).append(path)

            slug = slugify_type(raw_type)
            if slug:
                slug_to_types.setdefault(slug, set()).add(raw_type)

    for doc_id, paths in sorted(id_to_paths.items()):
        if len(paths) > 1:
            joined = ", ".join(str(p) for p in sorted(paths))
            findings.append(
                LintFinding(
                    severity=ERROR,
                    message=f"duplicate id {doc_id!r} in: {joined}",
                )
            )

    for slug, types in sorted(slug_to_types.items()):
        if len(types) > 1:
            joined = ", ".join(repr(t) for t in sorted(types))
            findings.append(
                LintFinding(
                    severity=WARNING,
                    message=(
                        f"type-slug collision: {joined} all slugify to {slug!r}"
                    ),
                )
            )

    return LintResult(findings=tuple(findings))


def format_findings(result: LintResult) -> str:
    return "\n".join(f"{f.severity}: {f.message}" for f in result.findings)


def run_lint(roots: str | None = None, owner: str | None = None) -> int:
    config = resolve_config(flag_roots=roots, flag_owner=owner)
    result = lint(config)
    for finding in result.findings:
        print(f"{finding.severity}: {finding.message}", file=sys.stderr)
    print(
        f"okf-mcp-lint: owner={config.owner!r} "
        f"roots={len(config.roots)} "
        f"errors={len(result.errors)} warnings={len(result.warnings)}",
        file=sys.stderr,
    )
    return result.exit_code


__all__ = [
    "ERROR",
    "WARNING",
    "LintFinding",
    "LintResult",
    "format_findings",
    "lint",
    "run_lint",
]
