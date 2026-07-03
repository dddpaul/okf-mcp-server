"""Shallow-clone owner repos into the gateway cache and refresh them in place.

Content served by the gateway originates here — a real ``git clone`` into a
gateway-owned cache directory, never a mount of the source tree. The clone is
shallow (``--depth 1``) at a single ref, shelling out to ``git`` via
``subprocess`` in the same style as ``config._git_toplevel``.

Once cloned, an owner is refreshed in place by :func:`fetch_and_reset`, which
shallow-fetches the ref and hard-resets onto it so a plain new commit and a
force-push both converge to the source tip; :func:`head_commit` reports the
resulting commit for change detection and the ``/refresh`` summary.

South auth (US-004): the read-only git-host token is injected into the clone and
fetch URLs *per invocation* by :func:`build_authenticated_url`, which resolves
``servers.yaml`` ``credentials`` by host. The token never touches the stored
remote — the checkout's ``origin`` is reset to the clean URL after a clone and
fetches pass the authenticated URL explicitly — and it is redacted from any
subprocess error so it cannot leak through logs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from .registry import Credential


class CredentialError(RuntimeError):
    """Raised when a git host has a credential entry but its token env is unset.

    Distinct from "no credential entry" (which is a valid unauthenticated clone):
    a configured credential whose ``token_env`` variable is missing or empty is
    an operator misconfiguration, so it fails fast with an actionable message
    rather than silently falling back to an unauthenticated clone that a private
    host would reject anyway.
    """


def build_authenticated_url(
    url: str, credentials: Mapping[str, Credential], env: Mapping[str, str]
) -> str:
    """Inject a per-host read-only token into ``url`` when a credential matches.

    The owner ``url`` from ``servers.yaml`` is provider-neutral and credential
    resolution keys purely off its host: the matching ``credentials[host]`` entry
    (if any) supplies ``token_user`` and the ``token_env`` variable holding the
    token, which are woven into ``https://<token_user>:<token>@host/...``. Both
    are percent-encoded so a token containing URL-significant characters (``@``,
    ``:``, ``/``) still produces a valid, unambiguous URL.

    Args:
        url: Clean owner git URL (no embedded credentials).
        credentials: Per-host credentials, keyed by host, from the registry.
        env: Environment mapping the token is read from (e.g. ``os.environ``).

    Returns:
        The authenticated URL when a credential matches the host; otherwise the
        original ``url`` unchanged (so public repos clone unauthenticated).

    Raises:
        CredentialError: If a credential entry matches the host but its
            ``token_env`` variable is unset or empty.
    """
    parts = urlsplit(url)
    host = parts.hostname
    if host is None:
        return url
    cred = credentials.get(host)
    if cred is None:
        return url  # no entry for this host -> unauthenticated (public repos work)
    token = env.get(cred.token_env, "")
    if not token:
        raise CredentialError(
            f"credential for host {host!r} reads its token from environment "
            f"variable {cred.token_env!r}, which is unset or empty; set it or "
            f"remove the credentials entry for {host!r}"
        )
    userinfo = f"{quote(cred.token_user, safe='')}:{quote(token, safe='')}"
    netloc = f"{userinfo}@{host}"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _run_git(
    args: list[str], *, redact: tuple[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a git command, redacting an injected token from any failure output.

    Args:
        args: The full ``git`` argument vector.
        redact: Optional ``(secret, replacement)`` pair; on failure every
            occurrence of ``secret`` (the authenticated URL) in the command and
            captured output is replaced with ``replacement`` (the clean URL) so
            the token never surfaces in a raised :class:`~subprocess.CalledProcessError`.

    Returns:
        The completed process.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero (with the
            token redacted when ``redact`` is given).
    """
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        if redact is None:
            raise
        secret, clean = redact
        safe_cmd = [str(part).replace(secret, clean) for part in exc.cmd]
        safe_stdout = (exc.output or "").replace(secret, clean)
        safe_stderr = (exc.stderr or "").replace(secret, clean)
        raise subprocess.CalledProcessError(
            exc.returncode, safe_cmd, output=safe_stdout, stderr=safe_stderr
        ) from None


def clone_owner(
    url: str,
    ref: str,
    dest: Path,
    *,
    credentials: Mapping[str, Credential] | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Shallow-clone ``url`` at ``ref`` into ``dest`` and return the checkout.

    Any existing checkout at ``dest`` is removed first so the clone is
    reproducible across gateway restarts. The clone is ``--depth 1`` at the
    single ``ref`` (a branch or tag). When a credential matches the host the
    fetch runs against the authenticated URL, but the stored ``origin`` is then
    reset to the clean ``url`` so the token never persists in ``.git/config``.

    Args:
        url: Clean git URL to clone (e.g. ``file:///path/to/repo.git`` or https).
        ref: Branch or tag to check out.
        dest: Target directory for the checkout.
        credentials: Per-host credentials from the registry; defaults to none.
        env: Environment the token is read from; defaults to ``os.environ``.

    Returns:
        The checkout directory (``dest``).

    Raises:
        CredentialError: If a matching credential's token env var is unset.
        subprocess.CalledProcessError: If a ``git`` invocation fails (token
            redacted from the error).
    """
    resolved_env = env if env is not None else os.environ
    auth_url = build_authenticated_url(url, credentials or {}, resolved_env)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_git(
        ["git", "clone", "--depth", "1", "--branch", ref, auth_url, str(dest)],
        redact=(auth_url, url) if auth_url != url else None,
    )
    if auth_url != url:
        # Never persist the token: reset origin to the clean URL (AC: clean remote).
        _run_git(["git", "-C", str(dest), "remote", "set-url", "origin", url])
    return dest


def fetch_and_reset(
    checkout: Path,
    ref: str,
    url: str,
    *,
    credentials: Mapping[str, Credential] | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Refresh an existing ``checkout`` to the source tip of ``ref`` in place.

    Shallow-fetches ``ref`` from the (possibly authenticated) ``url`` and
    hard-resets the working tree onto the fetched commit, keeping the clone at
    ``--depth 1``. The URL is passed explicitly rather than relying on the stored
    ``origin`` (which is intentionally credential-free), so the token is supplied
    per invocation only. Resetting onto ``FETCH_HEAD`` (rather than
    fast-forwarding) makes a normal new commit and a force-push converge
    identically to whatever the source now points at.

    Args:
        checkout: Existing shallow clone to refresh (the ``dest`` of a prior
            :func:`clone_owner`).
        ref: Branch or tag to fetch and reset onto.
        url: Clean git URL of the owner; a matching credential is injected for
            the fetch only.
        credentials: Per-host credentials from the registry; defaults to none.
        env: Environment the token is read from; defaults to ``os.environ``.

    Raises:
        CredentialError: If a matching credential's token env var is unset.
        subprocess.CalledProcessError: If the ``git fetch`` or ``git reset``
            invocation fails (token redacted from the error).
    """
    resolved_env = env if env is not None else os.environ
    auth_url = build_authenticated_url(url, credentials or {}, resolved_env)
    _run_git(
        ["git", "-C", str(checkout), "fetch", "--depth", "1", auth_url, ref],
        redact=(auth_url, url) if auth_url != url else None,
    )
    _run_git(["git", "-C", str(checkout), "reset", "--hard", "FETCH_HEAD"])


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
    result = _run_git(["git", "-C", str(checkout), "rev-parse", "HEAD"])
    return result.stdout.strip()


__all__ = [
    "CredentialError",
    "build_authenticated_url",
    "clone_owner",
    "fetch_and_reset",
    "head_commit",
]
