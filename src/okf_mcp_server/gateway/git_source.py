"""Shallow-clone owner repos into the gateway cache.

Content served by the gateway originates here — a real ``git clone`` into a
gateway-owned cache directory, never a mount of the source tree. The clone is
shallow (``--depth 1``) at a single ref, shelling out to ``git`` via
``subprocess`` in the same style as ``config._git_toplevel``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def clone_owner(url: str, ref: str, dest: Path) -> Path:
    """Shallow-clone ``url`` at ``ref`` into ``dest`` and return the checkout.

    Any existing checkout at ``dest`` is removed first so the clone is
    reproducible across gateway restarts. The clone is ``--depth 1`` at the
    single ``ref`` (a branch or tag).

    Args:
        url: Git URL to clone (e.g. ``file:///path/to/repo.git`` or an https URL).
        ref: Branch or tag to check out.
        dest: Target directory for the checkout.

    Returns:
        The checkout directory (``dest``).

    Raises:
        subprocess.CalledProcessError: If the ``git clone`` invocation fails.
    """
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, url, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


__all__ = ["clone_owner"]
