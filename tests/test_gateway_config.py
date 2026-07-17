"""US-005: the global ``GET /config`` effective-configuration endpoint.

Every test is offline and network-free. The endpoint reports only *effective*
config (registry + process settings) and never clones, so the app is driven with
Starlette's :class:`TestClient` **without** entering its lifespan — no owner
background clone is ever started. Owner URLs use the ``.invalid`` TLD purely as
inert data. A secret token is set in the environment to prove the endpoint emits
credential env-var *names* only, never the resolved token value.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from okf_mcp_server.gateway import create_app
from okf_mcp_server.gateway.registry import Credential, Defaults, OwnerSpec, Registry

DEFAULT_REF = "main"
DEFAULT_TTL = 60
NORTH_TOKEN = "north-secret-token"  # shared bearer token for the auth-gate test
GIT_TOKEN_ENV = "OKF_GIT_TOKEN_BITBUCKET"
GIT_TOKEN_SECRET = "super-secret-token-value"  # MUST never appear in /config output
CREDENTIAL_HOST = "bitbucket.example.invalid"


def _make_registry() -> Registry:
    """A registry exercising both owner resolution paths and one credential.

    ``acme`` omits ``ref``/``ttl`` (so it must inherit the ``defaults`` block);
    ``beta`` overrides both. One host carries a credential whose ``token_env``
    names an environment variable that the endpoint must not resolve.
    """
    return Registry(
        defaults=Defaults(ref=DEFAULT_REF, ttl=DEFAULT_TTL),
        owners={
            "acme": OwnerSpec(url="https://git.example.invalid/acme.git"),
            "beta": OwnerSpec(
                url=f"https://{CREDENTIAL_HOST}/beta.git",
                ref="release",
                ttl=120,
            ),
        },
        credentials={
            CREDENTIAL_HOST: Credential(
                token_env=GIT_TOKEN_ENV, token_user="x-token-auth"
            ),
        },
    )


def _make_app(tmp_path: Path, *, auth_token: str | None = None) -> Starlette:
    return create_app(
        _make_registry(),
        tmp_path / "cache",
        auth_token=auth_token,
        servers_path=tmp_path / "servers.yaml",
        host="0.0.0.0",
        port=8080,
    )


def test_config_default_is_json_with_top_level_keys(tmp_path: Path) -> None:
    response = TestClient(_make_app(tmp_path)).get("/config")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"process", "defaults", "owners", "credentials"}
    assert body["defaults"] == {"ref": DEFAULT_REF, "ttl": DEFAULT_TTL}


def test_config_process_block_reports_runtime_settings(tmp_path: Path) -> None:
    process = TestClient(_make_app(tmp_path)).get("/config").json()["process"]

    assert set(process) == {
        "servers_path",
        "cache_dir",
        "host",
        "port",
        "auth_required",
    }
    assert process["servers_path"] == str(tmp_path / "servers.yaml")
    assert process["cache_dir"] == str(tmp_path / "cache")
    assert process["host"] == "0.0.0.0"
    assert process["port"] == 8080
    assert process["auth_required"] is False  # this app was built without a token


def test_config_owners_resolved_against_defaults(tmp_path: Path) -> None:
    owners = TestClient(_make_app(tmp_path)).get("/config").json()["owners"]

    # acme omits ref/ttl -> inherits the defaults block verbatim.
    assert owners["acme"] == {
        "url": "https://git.example.invalid/acme.git",
        "ref": DEFAULT_REF,
        "ttl": DEFAULT_TTL,
    }
    # beta overrides both -> its own values win over defaults.
    assert owners["beta"] == {
        "url": f"https://{CREDENTIAL_HOST}/beta.git",
        "ref": "release",
        "ttl": 120,
    }


def test_config_credentials_expose_only_names_never_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real secret is present in the environment; the endpoint must ignore it.
    monkeypatch.setenv(GIT_TOKEN_ENV, GIT_TOKEN_SECRET)
    client = TestClient(_make_app(tmp_path))

    response = client.get("/config")
    yaml_response = client.get("/config", params={"format": "yaml"})

    assert response.status_code == 200
    creds = response.json()["credentials"][CREDENTIAL_HOST]
    assert creds == {"token_env": GIT_TOKEN_ENV, "token_user": "x-token-auth"}
    # The resolved token value leaks in neither serialization.
    assert GIT_TOKEN_SECRET not in response.text
    assert GIT_TOKEN_SECRET not in yaml_response.text


def test_config_yaml_round_trips_to_json_structure(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))

    json_body = client.get("/config").json()
    yaml_response = client.get("/config", params={"format": "yaml"})

    assert yaml_response.status_code == 200
    assert "process:" in yaml_response.text  # block YAML, not the JSON serialization
    assert yaml.safe_load(yaml_response.text) == json_body


def test_config_unsupported_format_returns_400(tmp_path: Path) -> None:
    response = TestClient(_make_app(tmp_path)).get("/config", params={"format": "xml"})

    assert response.status_code == 400


def test_config_is_gated_by_bearer_token_while_healthz_stays_open(
    tmp_path: Path,
) -> None:
    client = TestClient(_make_app(tmp_path, auth_token=NORTH_TOKEN))

    missing = client.get("/config")
    wrong = client.get("/config", headers={"Authorization": "Bearer not-the-token"})
    correct = client.get(
        "/config", headers={"Authorization": f"Bearer {NORTH_TOKEN}"}
    )
    health = client.get("/healthz")

    assert missing.status_code == 401  # no token -> rejected before the handler
    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert correct.json()["process"]["auth_required"] is True
    assert NORTH_TOKEN not in correct.text  # north token itself is never echoed back
    assert health.status_code == 200  # health check stays open with auth enabled
    assert health.text == "ok"
