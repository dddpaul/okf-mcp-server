"""Unit tests for the servers.yaml registry parser (US-002).

Covers parsing the three sections (defaults, owners, credentials), per-owner
ref/ttl fallback to the defaults block, and the fail-fast validation-error
cases (missing / malformed / empty / schema-invalid registries).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from okf_mcp_server.gateway.registry import (
    DEFAULT_REF,
    DEFAULT_TTL,
    RegistryError,
    load_registry,
)

VALID_YAML = """\
defaults:
  ref: main
  ttl: 60
owners:
  acme:
    url: file:///srv/acme.git
  beta:
    url: file:///srv/beta.git
    ref: release
    ttl: 120
credentials:
  bitbucket.corp:
    token_env: OKF_GIT_TOKEN_BITBUCKET
    token_user: x-token-auth
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "servers.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_owners_defaults_and_credentials(tmp_path: Path) -> None:
    reg = load_registry(_write(tmp_path, VALID_YAML))

    assert set(reg.owners) == {"acme", "beta"}
    assert reg.defaults.ref == "main"
    assert reg.defaults.ttl == 60
    cred = reg.credentials["bitbucket.corp"]
    assert cred.token_env == "OKF_GIT_TOKEN_BITBUCKET"
    assert cred.token_user == "x-token-auth"


def test_owner_without_ref_ttl_inherits_defaults(tmp_path: Path) -> None:
    reg = load_registry(_write(tmp_path, VALID_YAML))

    acme = reg.resolve("acme")
    assert acme is not None
    assert acme.url == "file:///srv/acme.git"
    assert acme.ref == "main"  # inherited from defaults
    assert acme.ttl == 60  # inherited from defaults


def test_owner_overrides_defaults(tmp_path: Path) -> None:
    reg = load_registry(_write(tmp_path, VALID_YAML))

    beta = reg.resolve("beta")
    assert beta is not None
    assert beta.ref == "release"
    assert beta.ttl == 120


def test_defaults_block_is_optional(tmp_path: Path) -> None:
    reg = load_registry(
        _write(tmp_path, "owners:\n  solo:\n    url: file:///srv/solo.git\n")
    )

    solo = reg.resolve("solo")
    assert solo is not None
    assert solo.ref == DEFAULT_REF  # built-in fallback (main)
    assert solo.ttl == DEFAULT_TTL  # built-in fallback (60)


def test_omitted_ttl_defaults_to_60_seconds(tmp_path: Path) -> None:
    # US-003 AC#8: with both the owner ttl and defaults.ttl omitted, the
    # effective TTL is 60s. Pin the literal so a change to the default is caught
    # (test_defaults_block_is_optional only compares against the symbol).
    reg = load_registry(
        _write(tmp_path, "owners:\n  solo:\n    url: file:///srv/solo.git\n")
    )

    resolved = reg.resolve("solo")
    assert resolved is not None
    assert resolved.ttl == 60


def test_credentials_section_is_optional(tmp_path: Path) -> None:
    reg = load_registry(
        _write(tmp_path, "owners:\n  solo:\n    url: file:///srv/solo.git\n")
    )

    assert reg.credentials == {}


def test_resolve_unregistered_owner_returns_none(tmp_path: Path) -> None:
    reg = load_registry(_write(tmp_path, VALID_YAML))

    assert reg.resolve("ghost") is None


def test_missing_file_raises_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError) as excinfo:
        load_registry(tmp_path / "does-not-exist.yaml")

    assert "not found" in str(excinfo.value)


def test_malformed_yaml_raises_registry_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, "owners: [unclosed\n"))


def test_non_mapping_yaml_raises_registry_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, "just a bare string\n"))


def test_empty_file_raises_registry_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, ""))


def test_no_owners_raises_registry_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, "defaults:\n  ref: main\n"))


def test_owner_missing_url_raises_registry_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, "owners:\n  acme: {}\n"))


def test_unknown_field_raises_registry_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(
            _write(tmp_path, "owners:\n  acme:\n    url: x\n    bogus: 1\n")
        )


def test_non_positive_ttl_raises_registry_error(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, "owners:\n  acme:\n    url: x\n    ttl: 0\n"))


def test_credential_missing_token_user_raises_registry_error(tmp_path: Path) -> None:
    text = (
        "owners:\n  acme:\n    url: x\n"
        "credentials:\n  host:\n    token_env: OKF_GIT_TOKEN\n"
    )
    with pytest.raises(RegistryError):
        load_registry(_write(tmp_path, text))
