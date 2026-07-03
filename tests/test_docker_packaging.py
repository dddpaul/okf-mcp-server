"""Offline gating checks for the Docker packaging (US-005, TASK-8).

These do not require Docker: the ``Dockerfile`` and ``docker-compose.yml`` are
parsed and their required properties asserted directly — the offline, always-on
gate that AC #3/#9 call for. When a ``docker`` binary is present, ``docker
compose config`` is additionally run to validate the compose file; it is skipped
otherwise (CI and the dev sandbox have no Docker). The real ``docker build`` /
``docker compose up -d`` stays a documented manual step because it pulls base
images and clones owner repos over the network.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from okf_mcp_server.gateway.registry import load_registry

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SERVERS = REPO_ROOT / "servers.yaml"
GITIGNORE = REPO_ROOT / ".gitignore"


def _compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _gateway_service() -> dict[str, Any]:
    return _compose()["services"]["gateway"]


def _env_file_paths(service: dict[str, Any]) -> set[str]:
    """Normalize the compose ``env_file`` (string / list / long-form) to paths."""
    raw = service.get("env_file", [])
    entries = [raw] if isinstance(raw, (str, dict)) else raw
    paths: set[str] = set()
    for entry in entries:
        paths.add(entry["path"] if isinstance(entry, dict) else entry)
    return paths


def _split_volume(mount: str) -> tuple[str, str, str]:
    """Split a ``src:dst[:mode]`` short-form volume into its parts."""
    parts = mount.split(":")
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], parts[2]


def _env_pairs() -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines from .env.example, ignoring comments/blanks."""
    pairs: dict[str, str] = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        pairs[key.strip()] = value.strip()
    return pairs


def test_dockerfile_slim_base_with_git_and_uv() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    from_lines = [ln for ln in text.splitlines() if ln.startswith("FROM ")]
    assert any("python:" in ln and "slim" in ln for ln in from_lines), from_lines
    assert "git" in text  # apt-get install git for runtime clone/fetch
    assert "uv" in text  # dependency install via uv


def test_dockerfile_runs_gateway_console_script() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    cmd_lines = [ln for ln in text.splitlines() if ln.startswith("CMD")]
    assert any("okf-mcp-gateway" in ln for ln in cmd_lines), cmd_lines


def test_compose_restart_policy_is_unless_stopped() -> None:
    assert _gateway_service()["restart"] == "unless-stopped"


def test_compose_publishes_8080() -> None:
    ports = [str(p) for p in _gateway_service()["ports"]]
    assert "8080:8080" in ports, ports


def test_compose_uses_env_file_dotenv() -> None:
    assert ".env" in _env_file_paths(_gateway_service())


def test_compose_mounts_named_cache_volume() -> None:
    compose = _compose()
    service = compose["services"]["gateway"]
    named = set(compose.get("volumes", {}))
    assert named, "expected a top-level named volume for the checkout cache"
    mounted_named = {
        src
        for src, _dst, _mode in map(_split_volume, service["volumes"])
        if src in named
    }
    assert mounted_named, "no named volume is mounted into the gateway service"


def test_compose_mounts_servers_yaml_read_only() -> None:
    mounts = [_split_volume(v) for v in _gateway_service()["volumes"]]
    servers = [(src, dst, mode) for src, dst, mode in mounts if "servers.yaml" in src]
    assert servers, "servers.yaml is not mounted"
    assert all(mode == "ro" for _src, _dst, mode in servers), servers


def test_compose_healthcheck_hits_healthz() -> None:
    test = _gateway_service()["healthcheck"]["test"]
    joined = " ".join(test) if isinstance(test, list) else str(test)
    assert "/healthz" in joined, test


def test_sample_servers_yaml_validates() -> None:
    registry = load_registry(SERVERS)
    assert registry.owners, "sample servers.yaml declares no owners"
    # Credentials name an env var, never a token value (no secrets committed).
    for cred in registry.credentials.values():
        assert cred.token_env.startswith("OKF_GIT_TOKEN_"), cred.token_env


def test_env_example_has_required_keys_and_no_secrets() -> None:
    pairs = _env_pairs()
    assert "OKF_GATEWAY_TOKEN" in pairs, pairs
    assert any(k.startswith("OKF_GIT_TOKEN_") for k in pairs), pairs
    # Every value is empty: the template carries key names, never real secrets.
    assert all(value == "" for value in pairs.values()), pairs


def test_gitignore_excludes_dotenv_but_tracks_example() -> None:
    lines = {ln.strip() for ln in GITIGNORE.read_text(encoding="utf-8").splitlines()}
    assert ".env" in lines, "real .env must be gitignored"
    assert ".env.example" not in lines, ".env.example must stay tracked"
    assert ENV_EXAMPLE.exists()


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")
def test_docker_compose_config_validates() -> None:
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
