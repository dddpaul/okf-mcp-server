"""Tests for okf_mcp_server.config (owner + roots resolver)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from okf_mcp_server.config import (
    DEFAULT_ROOTS,
    ENV_OWNER,
    ENV_ROOTS,
    ServerConfig,
    resolve_config,
)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def _make_repo(parent: Path, name: str) -> Path:
    repo = parent / name
    repo.mkdir()
    _git_init(repo)
    return repo


def test_resolve_config_owner_from_git_toplevel(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "my-owner")
    cfg = resolve_config(env={}, cwd=repo)
    assert isinstance(cfg, ServerConfig)
    assert cfg.owner == "my-owner"


def test_resolve_config_owner_from_toplevel_when_cwd_is_subdir(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "outer")
    sub = repo / "nested"
    sub.mkdir()
    cfg = resolve_config(env={}, cwd=sub)
    assert cfg.owner == "outer"


def test_resolve_config_fallback_to_cwd_basename_when_not_git(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    non_repo = tmp_path / "bare"
    non_repo.mkdir()
    cfg = resolve_config(env={}, cwd=non_repo)
    assert cfg.owner == "bare"
    err = capsys.readouterr().err
    assert "not a git repo" in err
    assert "bare" in err


def test_resolve_config_uses_default_roots_relative_to_toplevel(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "sample")
    for sub in DEFAULT_ROOTS:
        (repo / sub).mkdir(parents=True)
    cfg = resolve_config(env={}, cwd=repo)
    expected = tuple((repo / r).resolve() for r in DEFAULT_ROOTS)
    assert cfg.roots == expected


def test_resolve_config_flag_overrides_env_and_default(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "sample")
    (repo / "from-flag").mkdir()
    (repo / "from-env").mkdir()
    cfg = resolve_config(
        flag_roots="from-flag",
        env={ENV_ROOTS: "from-env"},
        cwd=repo,
    )
    assert cfg.roots == ((repo / "from-flag").resolve(),)


def test_resolve_config_flag_splits_on_comma(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "sample")
    (repo / "a").mkdir()
    (repo / "b").mkdir()
    cfg = resolve_config(flag_roots="a,b", env={}, cwd=repo)
    assert cfg.roots == ((repo / "a").resolve(), (repo / "b").resolve())


def test_resolve_config_env_splits_on_colon(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "sample")
    (repo / "x").mkdir()
    (repo / "y").mkdir()
    cfg = resolve_config(env={ENV_ROOTS: "x:y"}, cwd=repo)
    assert cfg.roots == ((repo / "x").resolve(), (repo / "y").resolve())


def test_resolve_config_skips_missing_roots_with_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _make_repo(tmp_path, "sample")
    (repo / "exists").mkdir()
    cfg = resolve_config(flag_roots="exists,does-not-exist", env={}, cwd=repo)
    assert cfg.roots == ((repo / "exists").resolve(),)
    err = capsys.readouterr().err
    assert "does-not-exist" in err
    assert "skipping" in err


def test_resolve_config_blank_flag_falls_through_to_env(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "sample")
    (repo / "from-env").mkdir()
    cfg = resolve_config(
        flag_roots="   ",
        env={ENV_ROOTS: "from-env"},
        cwd=repo,
    )
    assert cfg.roots == ((repo / "from-env").resolve(),)


def test_resolve_config_blank_env_falls_through_to_default(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "sample")
    for sub in DEFAULT_ROOTS:
        (repo / sub).mkdir(parents=True)
    cfg = resolve_config(env={ENV_ROOTS: "   "}, cwd=repo)
    expected = tuple((repo / r).resolve() for r in DEFAULT_ROOTS)
    assert cfg.roots == expected


def test_resolve_config_flag_resolves_relative_to_toplevel_not_cwd(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path, "sample")
    (repo / "design").mkdir()
    sub = repo / "subdir"
    sub.mkdir()
    cfg = resolve_config(flag_roots="design", env={}, cwd=sub)
    assert cfg.roots == ((repo / "design").resolve(),)


def test_resolve_config_owner_flag_overrides_git_toplevel(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "workspace")
    cfg = resolve_config(flag_owner="stacks", env={}, cwd=repo)
    assert cfg.owner == "stacks"


def test_resolve_config_owner_env_overrides_git_toplevel(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "workspace")
    cfg = resolve_config(env={ENV_OWNER: "stacks"}, cwd=repo)
    assert cfg.owner == "stacks"


def test_resolve_config_owner_flag_overrides_env(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "workspace")
    cfg = resolve_config(
        flag_owner="from-flag",
        env={ENV_OWNER: "from-env"},
        cwd=repo,
    )
    assert cfg.owner == "from-flag"


def test_resolve_config_owner_blank_flag_falls_through_to_env(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "workspace")
    cfg = resolve_config(
        flag_owner="   ",
        env={ENV_OWNER: "from-env"},
        cwd=repo,
    )
    assert cfg.owner == "from-env"


def test_resolve_config_owner_blank_env_falls_through_to_toplevel(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path, "from-git")
    cfg = resolve_config(env={ENV_OWNER: "   "}, cwd=repo)
    assert cfg.owner == "from-git"


def test_resolve_config_owner_flag_silences_cwd_fallback_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    non_repo = tmp_path / "bare"
    non_repo.mkdir()
    cfg = resolve_config(flag_owner="stacks", env={}, cwd=non_repo)
    assert cfg.owner == "stacks"
    err = capsys.readouterr().err
    assert "not a git repo" not in err


def test_resolve_config_owner_flag_is_trimmed(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "workspace")
    cfg = resolve_config(flag_owner="  stacks  ", env={}, cwd=repo)
    assert cfg.owner == "stacks"


def test_base_dir_overrides_cwd_for_git_toplevel_and_roots(tmp_path: Path) -> None:
    consumer = _make_repo(tmp_path, "consumer")
    (consumer / "design").mkdir()
    canon = _make_repo(tmp_path, "canon")
    (canon / "design").mkdir()
    shim_dir = canon / "mcp"
    shim_dir.mkdir()
    cfg = resolve_config(env={}, cwd=consumer, base_dir=shim_dir)
    assert cfg.owner == "canon"
    assert cfg.roots == ((canon / "design").resolve(),)


def test_base_dir_default_none_matches_cwd_behavior(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "sample")
    (repo / "design").mkdir()
    cfg_default = resolve_config(env={}, cwd=repo)
    cfg_explicit_none = resolve_config(env={}, cwd=repo, base_dir=None)
    assert cfg_default == cfg_explicit_none


def test_base_dir_owner_chain_3rd_link_uses_base_dir_toplevel(tmp_path: Path) -> None:
    consumer = _make_repo(tmp_path, "consumer")
    canon = _make_repo(tmp_path, "canonical-repo")
    nested = canon / "src" / "pkg"
    nested.mkdir(parents=True)
    cfg = resolve_config(env={}, cwd=consumer, base_dir=nested)
    assert cfg.owner == "canonical-repo"


def test_base_dir_roots_resolved_relative_to_base_dir_toplevel(tmp_path: Path) -> None:
    consumer = _make_repo(tmp_path, "consumer")
    (consumer / "design").mkdir()
    canon = _make_repo(tmp_path, "canon")
    (canon / "backlog" / "docs").mkdir(parents=True)
    nested = canon / "deep" / "nest"
    nested.mkdir(parents=True)
    cfg = resolve_config(
        flag_roots="backlog/docs",
        env={},
        cwd=consumer,
        base_dir=nested,
    )
    assert cfg.roots == ((canon / "backlog" / "docs").resolve(),)


def test_base_dir_with_owner_flag_still_honors_flag(tmp_path: Path) -> None:
    consumer = _make_repo(tmp_path, "consumer")
    canon = _make_repo(tmp_path, "canon")
    cfg = resolve_config(flag_owner="explicit", env={}, cwd=consumer, base_dir=canon)
    assert cfg.owner == "explicit"


def test_base_dir_not_in_git_falls_back_to_cwd_owner(tmp_path: Path) -> None:
    non_repo = tmp_path / "bare"
    non_repo.mkdir()
    repo = _make_repo(tmp_path, "from-cwd")
    cfg = resolve_config(env={}, cwd=repo, base_dir=non_repo)
    assert cfg.owner == "from-cwd"
    assert cfg.roots == ()
