"""Shared git-backed fixtures for the stdio server and the gateway.

``sample_repo`` copies the static ``tests/fixtures/sample-project`` into a fresh
tmp dir and runs ``git init`` so that ``git rev-parse --show-toplevel`` yields a
path whose basename is ``sample`` (the expected owner). Doing so in the source
tree would pollute the parent repo's git state.

``make_bare_repo`` extends the same ``git init`` pattern to build a ``file://``
*bare* repo — a valid ``git clone`` source seeded with arbitrary files on a
known branch — for the gateway's git-sourced tests. It is reused by this and
later gateway tasks.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

FIXTURE_SRC = Path(__file__).resolve().parent / "fixtures" / "sample-project"

_GIT_IDENTITY = ["-c", "user.email=okf@test.local", "-c", "user.name=OKF Test"]


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("repos") / "sample"
    shutil.copytree(FIXTURE_SRC, target)
    subprocess.run(
        ["git", "init", "-q"],
        cwd=target,
        check=True,
    )
    return target


@dataclass(frozen=True)
class GitRepoFixture:
    """A ``file://`` bare git repo usable as a gateway clone source.

    Attributes:
        url: ``file://`` URL to the bare repo (pass to a ``git clone``).
        ref: Branch the seed commit was made on and that clones should check out.
        work_dir: The seed working tree that produced the bare repo.
        bare_dir: The bare repo directory itself.
    """

    url: str
    ref: str
    work_dir: Path
    bare_dir: Path


@pytest.fixture
def make_bare_repo(
    tmp_path_factory: pytest.TempPathFactory,
) -> Callable[..., GitRepoFixture]:
    """Return a factory that builds a ``file://`` bare-repo git source.

    The factory takes a mapping of ``relative path -> file content`` and an
    optional branch name, seeds a working tree with those files, commits them on
    that branch, and clones the tree into a bare repo. The returned
    :class:`GitRepoFixture` carries the ``file://`` clone URL, the branch, and
    both directories for later tasks that need to push follow-up commits.
    """

    def _make(files: dict[str, str], ref: str = "main") -> GitRepoFixture:
        base = tmp_path_factory.mktemp("gitsrc")
        work = base / "work"
        work.mkdir()
        subprocess.run(
            ["git", "-c", f"init.defaultBranch={ref}", "init", "-q"],
            cwd=work,
            check=True,
        )
        for rel, content in files.items():
            path = work / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        subprocess.run(["git", "add", "-A"], cwd=work, check=True)
        subprocess.run(
            ["git", *_GIT_IDENTITY, "commit", "-q", "-m", "seed"],
            cwd=work,
            check=True,
        )
        bare = base / "repo.git"
        subprocess.run(
            ["git", "clone", "--quiet", "--bare", str(work), str(bare)],
            check=True,
        )
        return GitRepoFixture(
            url=f"file://{bare}", ref=ref, work_dir=work, bare_dir=bare
        )

    return _make
