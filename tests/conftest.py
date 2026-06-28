"""Session-scoped fixture: copy the static sample-project into a tmp git repo.

The static fixture at ``tests/fixtures/sample-project`` is the canonical worked
example referenced from the README. We copy it into a fresh tmp dir and run
``git init`` so that ``git rev-parse --show-toplevel`` yields a path whose
basename is ``sample`` (the expected owner). Doing so in the source tree would
pollute the parent repo's git state.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

FIXTURE_SRC = Path(__file__).resolve().parent / "fixtures" / "sample-project"


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
