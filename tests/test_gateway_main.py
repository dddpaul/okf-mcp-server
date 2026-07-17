"""Entry-point wiring for okf-mcp-gateway (US-002).

Verifies that ``__main__.main`` loads the registry before serving: a missing
``servers.yaml`` fails fast with a non-zero exit and never reaches uvicorn, and a
valid one builds the multi-owner app and hands it to uvicorn. Both are offline —
``uvicorn.run`` is patched out so no socket is bound.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import GitRepoFixture
from starlette.applications import Starlette

from okf_mcp_server.gateway import __main__ as main_module


def test_main_exits_fast_on_missing_servers_yaml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setenv("OKF_GATEWAY_TOKEN", "north-secret")
    monkeypatch.setenv("OKF_GATEWAY_SERVERS", str(tmp_path / "missing.yaml"))
    monkeypatch.setenv("OKF_GATEWAY_CACHE_DIR", str(tmp_path / "cache"))

    with pytest.raises(SystemExit) as excinfo:
        main_module.main()

    assert excinfo.value.code == 1
    assert calls == []  # aborted before ever reaching uvicorn.run


def test_main_exits_fast_without_north_token(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_bare_repo({"docs/x.md": "# x\n"}, ref="main")
    servers = tmp_path / "servers.yaml"
    servers.write_text(f"owners:\n  acme:\n    url: {source.url}\n", encoding="utf-8")
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(main_module.uvicorn, "run", lambda *a, **k: calls.append(a))
    monkeypatch.delenv("OKF_GATEWAY_TOKEN", raising=False)  # no consumer auth token
    monkeypatch.setenv("OKF_GATEWAY_SERVERS", str(servers))
    monkeypatch.setenv("OKF_GATEWAY_CACHE_DIR", str(tmp_path / "cache"))

    with pytest.raises(SystemExit) as excinfo:
        main_module.main()

    assert excinfo.value.code == 1
    assert calls == []  # refuses to serve without a north bearer token


def test_main_builds_multi_owner_app_from_registry(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_bare_repo({"docs/x.md": "# x\n"}, ref="main")
    servers = tmp_path / "servers.yaml"
    servers.write_text(
        f"owners:\n  acme:\n    url: {source.url}\n", encoding="utf-8"
    )
    served: list[Starlette] = []
    monkeypatch.setattr(
        main_module.uvicorn, "run", lambda app, **k: served.append(app)
    )
    monkeypatch.setenv("OKF_GATEWAY_TOKEN", "north-secret")
    monkeypatch.setenv("OKF_GATEWAY_SERVERS", str(servers))
    monkeypatch.setenv("OKF_GATEWAY_CACHE_DIR", str(tmp_path / "cache"))

    main_module.main()

    assert len(served) == 1
    assert set(served[0].state.owners) == {"acme"}
    assert served[0].state.auth_required is True  # north bearer auth is wired on


def test_main_wires_process_config_onto_app_state(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_bare_repo({"docs/x.md": "# x\n"}, ref="main")
    servers = tmp_path / "servers.yaml"
    servers.write_text(f"owners:\n  acme:\n    url: {source.url}\n", encoding="utf-8")
    served: list[Starlette] = []
    monkeypatch.setattr(
        main_module.uvicorn, "run", lambda app, **k: served.append(app)
    )
    monkeypatch.setenv("OKF_GATEWAY_TOKEN", "north-secret")
    monkeypatch.setenv("OKF_GATEWAY_SERVERS", str(servers))
    monkeypatch.setenv("OKF_GATEWAY_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("OKF_GATEWAY_HOST", "127.0.0.1")
    monkeypatch.setenv("OKF_GATEWAY_PORT", "9000")

    main_module.main()

    assert len(served) == 1
    # main() resolves host/port and forwards servers_path so GET /config reports them.
    assert served[0].state.servers_path == servers
    assert served[0].state.host == "127.0.0.1"
    assert served[0].state.port == 9000
