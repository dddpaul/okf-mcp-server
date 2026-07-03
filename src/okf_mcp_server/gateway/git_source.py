"""Shallow-clone owner repos into the gateway cache and refresh them in place.

Content served by the gateway originates here — a real ``git clone`` into a
gateway-owned cache directory, never a mount of the source tree. The clone is
shallow (``--depth 1``) at a single ref, shelling out to ``git`` via
``subprocess`` in the same style as ``config._git_toplevel``.

Once cloned, an owner is refreshed in place by :func:`fetch_and_reset`, which
shallow-fetches the ref and hard-resets onto it so a plain new commit and a
force-push both converge to the source tip; :func:`head_commit` reports the
resulting commit for change detection and the ``/refresh`` summary.
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


def fetch_and_reset(checkout: Path, ref: str) -> None:
    """Refresh an existing ``checkout`` to the source tip of ``ref`` in place.

    Shallow-fetches ``ref`` from ``origin`` and hard-resets the working tree onto
    the fetched commit, keeping the clone at ``--depth 1``. Resetting onto
    ``FETCH_HEAD`` (rather than fast-forwarding) makes a normal new commit and a
    force-push converge identically to whatever the source now points at.

    Args:
        checkout: Existing shallow clone to refresh (the ``dest`` of a prior
            :func:`clone_owner`).
        ref: Branch or tag to fetch and reset onto.

    Raises:
        subprocess.CalledProcessError: If the ``git fetch`` or ``git reset``
            invocation fails.
    """
    subprocess.run(
        ["git", "-C", str(checkout), "fetch", "--depth", "1", "origin", ref],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "reset", "--hard", "FETCH_HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )


def head_commit(checkout: Path) -> str:
    """Return the full ``HEAD`` commit SHA of ``checkout``.

    Used both to detect whether a refresh changed the tree (so docs are reloaded
    only when the commit actually moved) and to report the served commit in the
    ``/refresh`` summary.

    Args:
        checkout: A git checkout directory.

    Returns:
        The 40-character ``HEAD`` commit SHA.

    Raises:
        subprocess.CalledProcessError: If the ``git rev-parse`` invocation fails.
    """
    result = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


__all__ = ["clone_owner", "fetch_and_reset", "head_commit"]
