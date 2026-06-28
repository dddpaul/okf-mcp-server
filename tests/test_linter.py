"""Tests for okf_mcp_server.linter (id-uniqueness + export validity)."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from okf_mcp_server import linter as linter_module
from okf_mcp_server.config import ServerConfig, resolve_config
from okf_mcp_server.linter import (
    ERROR,
    WARNING,
    LintFinding,
    LintResult,
    format_findings,
    lint,
    run_lint,
)
from okf_mcp_server.server import extract_id, slugify_type


def _write(dir: Path, name: str, body: str) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / name
    path.write_text(body, encoding="utf-8")
    return path


def _config(roots: tuple[Path, ...]) -> ServerConfig:
    return ServerConfig(owner="stacks", roots=roots)


def _front(meta_block: str, body: str = "Body.\n") -> str:
    return f"---\n{meta_block}---\n\n{body}"


def test_lint_passes_when_all_exported_docs_are_unique(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _write(docs, "doc-1 - One.md", _front("type: Reference\nexport: true\n"))
    _write(docs, "doc-2 - Two.md", _front("type: Reference\nexport: true\n"))
    result = lint(_config((docs,)))
    assert result.findings == ()
    assert result.exit_code == 0


def test_lint_ignores_files_without_export_true(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _write(docs, "draft.md", _front("type: Reference\n"))
    _write(docs, "off.md", _front("type: Reference\nexport: false\n"))
    result = lint(_config((docs,)))
    assert result.findings == ()


def test_lint_errors_on_duplicate_id_within_owner(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    a = _write(
        docs, "doc-1 - First.md", _front("type: Reference\nexport: true\n")
    )
    b = _write(
        docs, "doc-1 - Second.md", _front("type: Reference\nexport: true\n")
    )
    result = lint(_config((docs,)))
    assert result.exit_code == 1
    err_messages = [f.message for f in result.errors]
    assert len(err_messages) == 1
    msg = err_messages[0]
    assert "'doc-1'" in msg
    assert str(a) in msg
    assert str(b) in msg


def test_lint_errors_on_duplicate_id_across_roots(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    design = tmp_path / "design"
    a = _write(docs, "doc-1 - In docs.md", _front("type: Doc\nexport: true\n"))
    b = _write(
        design, "doc-1 - In design.md", _front("type: Design\nexport: true\n")
    )
    result = lint(_config((docs, design)))
    msg = result.errors[0].message
    assert str(a) in msg and str(b) in msg


def test_lint_errors_when_export_true_but_type_is_missing(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    p = _write(docs, "bad.md", _front("export: true\n"))
    result = lint(_config((docs,)))
    assert result.exit_code == 1
    assert len(result.errors) == 1
    assert str(p) in result.errors[0].message
    assert "type" in result.errors[0].message


def test_lint_errors_when_export_true_but_type_is_blank(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    p = _write(docs, "blank.md", _front("type: '   '\nexport: true\n"))
    result = lint(_config((docs,)))
    assert result.exit_code == 1
    assert str(p) in result.errors[0].message


def test_lint_warns_on_type_slug_collision_without_failing(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _write(
        docs,
        "doc-1 - A.md",
        _front("type: Strategy doc\nexport: true\n"),
    )
    _write(
        docs,
        "doc-2 - B.md",
        _front("type: Strategy-doc\nexport: true\n"),
    )
    result = lint(_config((docs,)))
    assert result.exit_code == 0
    assert result.errors == ()
    assert len(result.warnings) == 1
    warn = result.warnings[0].message
    assert "strategy-doc" in warn
    assert "'Strategy doc'" in warn
    assert "'Strategy-doc'" in warn


def test_lint_does_not_warn_when_same_type_string_used_twice(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _write(docs, "doc-1 - A.md", _front("type: Reference doc\nexport: true\n"))
    _write(docs, "doc-2 - B.md", _front("type: Reference doc\nexport: true\n"))
    result = lint(_config((docs,)))
    assert result.warnings == ()


def test_lint_collects_multiple_findings_in_one_pass(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _write(docs, "doc-1 - A.md", _front("type: Doc\nexport: true\n"))
    _write(docs, "doc-1 - B.md", _front("type: Doc\nexport: true\n"))
    _write(docs, "missing-type.md", _front("export: true\n"))
    _write(docs, "slug-a.md", _front("id: x\ntype: Strategy doc\nexport: true\n"))
    _write(docs, "slug-b.md", _front("id: y\ntype: Strategy-doc\nexport: true\n"))
    result = lint(_config((docs,)))
    assert len(result.errors) == 2
    assert len(result.warnings) == 1
    assert result.exit_code == 1


def test_lint_reuses_server_extract_id_for_frontmatter_id(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    a = _write(
        docs, "alpha.md", _front("id: shared\ntype: Doc\nexport: true\n")
    )
    b = _write(
        docs, "beta.md", _front("id: shared\ntype: Doc\nexport: true\n")
    )
    result = lint(_config((docs,)))
    msg = result.errors[0].message
    assert "'shared'" in msg and str(a) in msg and str(b) in msg


def test_lint_reuses_server_slugify_for_collision_detection(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    _write(docs, "doc-1 - A.md", _front("type: 'API Spec'\nexport: true\n"))
    _write(docs, "doc-2 - B.md", _front("type: 'api  spec!'\nexport: true\n"))
    result = lint(_config((docs,)))
    assert slugify_type("API Spec") == slugify_type("api  spec!")
    assert len(result.warnings) == 1
    assert "api-spec" in result.warnings[0].message


def test_lint_skips_missing_root(tmp_path: Path) -> None:
    docs = tmp_path / "exists"
    docs.mkdir()
    _write(docs, "doc-1 - A.md", _front("type: Doc\nexport: true\n"))
    result = lint(_config((docs,)))
    assert result.findings == ()


def test_lint_returns_zero_exit_for_empty_repo(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = lint(_config((empty,)))
    assert result.findings == ()
    assert result.exit_code == 0


def test_lint_result_exit_code_is_one_when_errors_present() -> None:
    r = LintResult(findings=(LintFinding(severity=ERROR, message="x"),))
    assert r.exit_code == 1


def test_lint_result_exit_code_is_zero_when_only_warnings() -> None:
    r = LintResult(findings=(LintFinding(severity=WARNING, message="x"),))
    assert r.exit_code == 0


def test_format_findings_emits_severity_prefix() -> None:
    r = LintResult(
        findings=(
            LintFinding(severity=ERROR, message="boom"),
            LintFinding(severity=WARNING, message="careful"),
        )
    )
    text = format_findings(r)
    assert "error: boom" in text
    assert "warning: careful" in text


def test_lint_recurses_into_subdirectories(tmp_path: Path) -> None:
    root = tmp_path / "design"
    _write(root, "top.md", _front("type: Design\nexport: true\n"))
    _write(root / "sub", "nested.md", _front("type: Design\nexport: true\n"))
    result = lint(_config((root,)))
    assert result.findings == ()


def test_lint_on_sample_fixture_passes(sample_repo: Path) -> None:
    config = resolve_config(env={}, cwd=sample_repo)
    result = lint(config)
    assert result.findings == ()
    assert result.exit_code == 0


def test_run_lint_returns_exit_code_and_writes_findings_to_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    design = tmp_path / "design"
    _write(design, "doc-1 - A.md", _front("type: Doc\nexport: true\n"))
    _write(design, "doc-1 - B.md", _front("type: Doc\nexport: true\n"))
    monkeypatch.chdir(tmp_path)
    exit_code = run_lint(roots="design")
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "error:" in captured.err
    assert "'doc-1'" in captured.err
    assert "errors=1" in captured.err


def test_run_lint_zero_exit_when_clean(
    sample_repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(sample_repo)
    exit_code = run_lint()
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "errors=0" in captured.err


def test_run_lint_owner_override_appears_in_summary(
    sample_repo: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(sample_repo)
    exit_code = run_lint(owner="stacks")
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "owner='stacks'" in captured.err


def test_linter_module_does_not_redefine_extract_id_or_slugify() -> None:
    src = inspect.getsource(linter_module)
    assert "def slugify_type" not in src
    assert "def extract_id" not in src
    assert extract_id.__module__ == "okf_mcp_server.server"
    assert slugify_type.__module__ == "okf_mcp_server.server"
