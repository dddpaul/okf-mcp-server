"""US-004 south auth: per-host git credential resolution and clean stored remote.

Every test is offline. The pure URL builder is exercised directly; ``clone_owner``
and ``fetch_and_reset`` are exercised against a fake ``subprocess.run`` so the
exact git argument vectors are asserted without a live authenticated host, and
the clean-remote invariant is also verified against a real ``file://`` clone by
reading its ``.git/config``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import GitRepoFixture

from okf_mcp_server.gateway import git_source
from okf_mcp_server.gateway.git_source import (
    CredentialError,
    build_authenticated_url,
    clone_owner,
    fetch_and_reset,
)
from okf_mcp_server.gateway.registry import Credential

CREDS = {"git.corp": Credential(token_env="OKF_TOK", token_user="x-token-auth")}
ENV = {"OKF_TOK": "s3cr3t-token"}


def test_build_authenticated_url_injects_token_for_matching_host() -> None:
    result = build_authenticated_url("https://git.corp/acme.git", CREDS, ENV)

    assert result == "https://x-token-auth:s3cr3t-token@git.corp/acme.git"


def test_build_authenticated_url_no_matching_entry_returns_clean_url() -> None:
    # A host with no credentials entry clones unauthenticated (public repos work).
    result = build_authenticated_url("https://public.example/acme.git", CREDS, ENV)

    assert result == "https://public.example/acme.git"


def test_build_authenticated_url_preserves_port_and_path() -> None:
    result = build_authenticated_url("https://git.corp:8443/team/acme.git", CREDS, ENV)

    assert result == "https://x-token-auth:s3cr3t-token@git.corp:8443/team/acme.git"


def test_build_authenticated_url_percent_encodes_special_characters() -> None:
    creds = {"git.corp": Credential(token_env="OKF_TOK", token_user="x-token-auth")}
    env = {"OKF_TOK": "p@ss/w:rd"}

    result = build_authenticated_url("https://git.corp/acme.git", creds, env)

    # URL-significant characters in the token must be percent-encoded.
    assert result == "https://x-token-auth:p%40ss%2Fw%3Ard@git.corp/acme.git"


def test_build_authenticated_url_hostless_url_is_unchanged() -> None:
    # file:// URLs have no host, so they never match a credential entry.
    url = "file:///srv/git/acme.git"

    assert build_authenticated_url(url, CREDS, ENV) == url


def test_build_authenticated_url_missing_token_env_raises() -> None:
    with pytest.raises(CredentialError) as excinfo:
        build_authenticated_url("https://git.corp/acme.git", CREDS, {})

    message = str(excinfo.value)
    assert "OKF_TOK" in message  # names the unset env var so the operator can fix it
    assert "git.corp" in message


def _record_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> list[list[str]]:
    """Replace ``git_source.subprocess.run`` with a recorder of argv vectors."""
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(git_source.subprocess, "run", fake_run)
    return calls


def test_clone_owner_injects_token_but_stores_clean_remote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _record_runs(monkeypatch)
    dest = tmp_path / "acme"

    clone_owner(
        "https://git.corp/acme.git", "main", dest, credentials=CREDS, env=ENV
    )

    clone_cmd, set_url_cmd = calls
    # The clone fetches from the authenticated URL...
    assert clone_cmd == [
        "git", "clone", "--depth", "1", "--branch", "main",
        "https://x-token-auth:s3cr3t-token@git.corp/acme.git", str(dest),
    ]
    # ...then origin is reset to the CLEAN URL so no token persists (AC #5).
    assert set_url_cmd == [
        "git", "-C", str(dest), "remote", "set-url", "origin",
        "https://git.corp/acme.git",
    ]
    assert not any("s3cr3t-token" in part for part in set_url_cmd)


def test_clone_owner_unauthenticated_host_makes_no_set_url_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _record_runs(monkeypatch)
    dest = tmp_path / "acme"

    clone_owner(
        "https://public.example/acme.git", "main", dest, credentials=CREDS, env=ENV
    )

    # No credential match => a single plain clone, no remote rewrite.
    assert len(calls) == 1
    assert calls[0][-2] == "https://public.example/acme.git"


def test_fetch_and_reset_fetches_from_authenticated_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = _record_runs(monkeypatch)
    checkout = tmp_path / "acme"

    fetch_and_reset(
        checkout, "main", "https://git.corp/acme.git", credentials=CREDS, env=ENV
    )

    fetch_cmd, reset_cmd = calls
    assert fetch_cmd == [
        "git", "-C", str(checkout), "fetch", "--depth", "1",
        "https://x-token-auth:s3cr3t-token@git.corp/acme.git", "main",
    ]
    # The reset targets FETCH_HEAD and never touches the (clean) stored remote.
    assert reset_cmd == ["git", "-C", str(checkout), "reset", "--hard", "FETCH_HEAD"]


def test_clone_owner_redacts_token_from_git_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failing_run(
        args: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        # git echoes the remote URL (with the token) in its access errors.
        raise subprocess.CalledProcessError(
            128, list(args), output="", stderr=f"fatal: unable to access '{args[-2]}'"
        )

    monkeypatch.setattr(git_source.subprocess, "run", failing_run)
    dest = tmp_path / "acme"

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        clone_owner(
            "https://git.corp/acme.git", "main", dest, credentials=CREDS, env=ENV
        )

    exc = excinfo.value
    assert "s3cr3t-token" not in str(exc)
    assert "s3cr3t-token" not in " ".join(exc.cmd)
    assert "s3cr3t-token" not in (exc.stderr or "")
    # The clean URL survives so the failure is still debuggable.
    assert "https://git.corp/acme.git" in (exc.stderr or "")


def test_cloned_checkout_git_config_contains_no_credentials(
    make_bare_repo: Callable[..., GitRepoFixture], tmp_path: Path
) -> None:
    source = make_bare_repo({"docs/x.md": "# x\n"}, ref="main")
    dest = tmp_path / "acme"

    clone_owner(source.url, source.ref, dest)

    config_text = (dest / ".git" / "config").read_text(encoding="utf-8")
    assert source.url in config_text  # origin is the clean clone URL
    assert "@" not in config_text  # no embedded userinfo anywhere in the config
