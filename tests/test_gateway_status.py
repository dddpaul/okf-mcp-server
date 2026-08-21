"""US-006: the global ``GET /status`` live-runtime endpoint.

Every test is offline and network-free. Owner state that needs a real clone
(``serving``/``failed``/``loading``) is driven within the app lifespan against
``file://`` bare-repo fixtures over ``httpx.ASGITransport``, exactly like the
US-002/003 gateway tests; the pure format/auth cases reuse Starlette's
``TestClient`` *without* the lifespan, so no clone is started. Both clocks are
injected so ``last_pulled_at`` and ``last_pulled_age_seconds`` are deterministic.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import yaml
from conftest import FakeClock, GitRepoFixture, push_commit
from starlette.applications import Starlette
from starlette.testclient import TestClient

from okf_mcp_server.gateway import Registry, create_app
from okf_mcp_server.gateway import owner_cache as owner_cache_module
from okf_mcp_server.gateway.git_source import clone_owner
from okf_mcp_server.gateway.registry import Credential, OwnerSpec

REFERENCE_DOC = """---
export: true
type: Reference Doc
id: st-ref-1
title: Status Reference
description: Reference served under the status tests.
---
# Status Reference

Body of the status reference doc.
"""

DECISION_DOC = """---
export: true
type: Architecture Decision
id: st-adr-1
title: Status ADR
---
# Status ADR

The status decision body.
"""

# Two exported docs (+ one un-exported readme) => docs_loaded == 2 for a serving owner.
FIXTURE_FILES = {
    "docs/reference.md": REFERENCE_DOC,
    "design/adr.md": DECISION_DOC,
    "README.md": "# readme\n\nNo frontmatter, so it is never served.\n",
}

NORTH_TOKEN = "north-secret-token"  # shared bearer token for the auth-gate test
GIT_TOKEN_SECRET = "sekret-token-value-1234"  # MUST never surface in /status output
FAIL_HOST = "bitbucket.corp"
# The clean owner URL (as it appears in servers.yaml); the token below is what a
# clone-failure exception would embed, and what render-time scrubbing must remove.
BETA_URL = f"https://{FAIL_HOST}/beta.git"


def _failing_clone(
    fail_url: str, exc: Exception
) -> Callable[..., Path]:
    """A ``clone_owner`` stand-in that raises ``exc`` for ``fail_url``, else clones.

    Lets one owner's clone fail deterministically (driving its ``failed`` state)
    while any other owner in the same app clones for real.
    """
    real = clone_owner

    def _clone(
        url: str,
        ref: str,
        dest: Path,
        *,
        credentials: Mapping[str, Credential] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Path:
        if url == fail_url:
            raise exc
        return real(url, ref, dest, credentials=credentials, env=env)

    return _clone


async def _get_status_ready(
    app: Starlette, wait: tuple[str, ...], *, params: dict[str, str] | None = None
) -> httpx.Response:
    """GET ``/status`` inside the lifespan once every ``wait`` owner is ready."""
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://gateway.test"
        ) as client:
            for owner in wait:
                await asyncio.wait_for(
                    app.state.owners[owner].ready.wait(), timeout=15
                )
            return await client.get("/status", params=params or {})


def test_status_default_json_shape_and_summary(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    beta = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(
        Registry(
            owners={
                "acme": OwnerSpec(url=acme.url, ref=acme.ref),
                "beta": OwnerSpec(url=beta.url, ref=beta.ref),
            }
        ),
        tmp_path / "cache",
    )

    response = asyncio.run(_get_status_ready(app, ("acme", "beta")))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"summary", "owners"}
    assert body["summary"] == {"total": 2, "serving": 2, "loading": 0, "failed": 0}
    assert set(body["owners"]) == {"acme", "beta"}
    for entry in body["owners"].values():
        # A serving owner carries exactly the base keys (no error object). The
        # offline-fallback fields are always present; a healthy owner reports the
        # source as available and not stale.
        assert set(entry) == {
            "state",
            "ref",
            "served_commit",
            "source_available",
            "stale",
            "docs_loaded",
            "last_pulled_at",
            "last_pulled_age_seconds",
            "last_pull_attempt_at",
            "last_pull_error",
        }
        assert entry["state"] == "serving"
        assert entry["source_available"] is True
        assert entry["stale"] is False
        assert entry["last_pull_error"] is None
        assert entry["last_pull_attempt_at"] is not None  # stamped on the load pull


def test_status_serving_owner_reports_commit_docs_and_injected_clocks(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    clock = FakeClock()  # monotonic source: last_pulled is stamped at 0 on load
    fixed_wall = datetime(2026, 7, 17, 7, 46, 46, tzinfo=timezone.utc)
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url=acme.url, ref=acme.ref)}),
        tmp_path / "cache",
        clock=clock,
        wall_clock=lambda: fixed_wall.timestamp(),
    )

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                await asyncio.wait_for(
                    app.state.owners["acme"].ready.wait(), timeout=15
                )
                clock.advance(340)  # 340s of monotonic time since the load stamp
                return await client.get("/status")

    owner = asyncio.run(scenario()).json()["owners"]["acme"]

    assert owner["state"] == "serving"
    assert owner["ref"] == "main"
    assert owner["served_commit"] is not None
    int(owner["served_commit"], 16)  # a hex commit SHA
    assert owner["docs_loaded"] == 2
    # Fixed wall clock => exact ISO 8601 UTC timestamp.
    assert owner["last_pulled_at"] == "2026-07-17T07:46:46Z"
    # Monotonic age reflects exactly the injected advance.
    assert owner["last_pulled_age_seconds"] == 340


def test_status_failed_owner_is_scrubbed_and_counted(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    exc = RuntimeError(
        f"fatal: could not read from "
        f"https://x-token-auth:{GIT_TOKEN_SECRET}@{FAIL_HOST}/beta.git"
    )
    monkeypatch.setattr(
        owner_cache_module, "clone_owner", _failing_clone(BETA_URL, exc)
    )
    app = create_app(
        Registry(
            owners={
                "acme": OwnerSpec(url=acme.url, ref=acme.ref),
                "beta": OwnerSpec(url=BETA_URL, ref="release"),
            }
        ),
        tmp_path / "cache",
    )

    body = asyncio.run(_get_status_ready(app, ("acme", "beta"))).json()

    assert body["summary"] == {"total": 2, "serving": 1, "loading": 0, "failed": 1}
    beta = body["owners"]["beta"]
    assert beta["state"] == "failed"
    assert beta["ref"] == "release"
    assert beta["served_commit"] is None
    assert beta["docs_loaded"] == 0
    assert beta["last_pulled_at"] is None
    assert beta["last_pulled_age_seconds"] is None
    assert beta["error"]["type"] == "RuntimeError"
    assert beta["error"]["message"] == (
        f"fatal: could not read from https://***@{FAIL_HOST}/beta.git"
    )
    assert GIT_TOKEN_SECRET not in beta["error"]["message"]


def test_status_token_never_appears_in_body_json_or_yaml(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    exc = RuntimeError(
        f"remote: invalid credentials for "
        f"https://x-token-auth:{GIT_TOKEN_SECRET}@{FAIL_HOST}/beta.git"
    )
    monkeypatch.setattr(
        owner_cache_module, "clone_owner", _failing_clone(BETA_URL, exc)
    )
    app = create_app(
        Registry(
            owners={
                "acme": OwnerSpec(url=acme.url, ref=acme.ref),
                "beta": OwnerSpec(url=BETA_URL, ref="release"),
            }
        ),
        tmp_path / "cache",
    )

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                for owner in ("acme", "beta"):
                    await asyncio.wait_for(
                        app.state.owners[owner].ready.wait(), timeout=15
                    )
                json_resp = await client.get("/status")
                yaml_resp = await client.get("/status", params={"format": "yaml"})
                return json_resp, yaml_resp

    json_resp, yaml_resp = asyncio.run(scenario())

    # The token leaks in neither serialization; the userinfo is redacted, not the
    # whole URL dropped (host survives for debugging).
    assert GIT_TOKEN_SECRET not in json_resp.text
    assert GIT_TOKEN_SECRET not in yaml_resp.text
    assert "***@" in json_resp.text


def test_status_loading_owner_does_not_block(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow = make_bare_repo(FIXTURE_FILES, ref="main")
    release = threading.Event()
    real_clone = clone_owner

    def gated_clone(
        url: str,
        ref: str,
        dest: Path,
        *,
        credentials: Mapping[str, Credential] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> Path:
        if url == slow.url:  # block the slow owner's clone in its worker thread
            release.wait(timeout=30)
        return real_clone(url, ref, dest, credentials=credentials, env=env)

    monkeypatch.setattr(owner_cache_module, "clone_owner", gated_clone)
    app = create_app(
        Registry(owners={"slow": OwnerSpec(url=slow.url, ref=slow.ref)}),
        tmp_path / "cache",
    )

    async def scenario() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                try:
                    # The clone is still stuck; /status must answer without
                    # waiting on the owner's readiness.
                    return await asyncio.wait_for(client.get("/status"), timeout=10)
                finally:
                    release.set()  # let the clone finish for a clean shutdown

    body = asyncio.run(scenario()).json()

    assert body["summary"] == {"total": 1, "serving": 0, "loading": 1, "failed": 0}
    slow_entry = body["owners"]["slow"]
    assert slow_entry["state"] == "loading"
    assert slow_entry["served_commit"] is None
    assert slow_entry["docs_loaded"] == 0
    assert slow_entry["last_pulled_at"] is None
    assert slow_entry["last_pulled_age_seconds"] is None
    assert "error" not in slow_entry


def test_status_yaml_round_trips_and_unsupported_format_400(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    monkeypatch.setattr(
        owner_cache_module,
        "clone_owner",
        _failing_clone(BETA_URL, RuntimeError("boom")),
    )
    app = create_app(
        Registry(
            owners={
                "acme": OwnerSpec(url=acme.url, ref=acme.ref),
                "beta": OwnerSpec(url=BETA_URL, ref="release"),
            }
        ),
        tmp_path / "cache",
    )

    async def scenario() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                for owner in ("acme", "beta"):
                    await asyncio.wait_for(
                        app.state.owners[owner].ready.wait(), timeout=15
                    )
                json_resp = await client.get("/status")
                yaml_resp = await client.get("/status", params={"format": "yaml"})
                bad_resp = await client.get("/status", params={"format": "xml"})
                return json_resp, yaml_resp, bad_resp

    json_resp, yaml_resp, bad_resp = asyncio.run(scenario())

    assert yaml_resp.status_code == 200
    assert yaml_resp.headers["content-type"].startswith("application/yaml")
    assert "summary:" in yaml_resp.text  # block YAML, not the JSON serialization
    # YAML carries the same structure as the JSON body (including nulls + error).
    assert yaml.safe_load(yaml_resp.text) == json_resp.json()
    assert bad_resp.status_code == 400  # unsupported ?format= value


# A revised ADR body (same id/frontmatter) so a refresh moves the commit and
# changes ONLY this doc's bytes; the reference doc below stays byte-identical.
DECISION_DOC_V2 = """---
export: true
type: Architecture Decision
id: st-adr-1
title: Status ADR
---
# Status ADR

The status decision body, revised in a follow-up commit.
"""


def test_status_served_commit_advances_after_refresh_and_stable_hash_holds(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """A refresh onto a new commit advances served_commit (AC#3), yet a doc whose
    bytes did not change keeps its content_hash while a changed doc gets a new one
    (AC#4: identical content -> identical hash, enabling no-op-wake detection)."""
    source = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url=source.url, ref=source.ref)}),
        tmp_path / "cache",
    )

    def hash_of(doc_id: str) -> str:
        # content_hash is the exact value read_resource/list_resources surface in
        # each resource's _meta, read straight off the owner's served docs.
        docs = app.state.owners["acme"].cache.docs
        return next(d for d in docs if d.id == doc_id).content_hash

    async def scenario() -> dict[str, str]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                await asyncio.wait_for(
                    app.state.owners["acme"].ready.wait(), timeout=15
                )
                before = (await client.get("/status")).json()["owners"]["acme"]
                captured = {
                    "commit_before": before["served_commit"],
                    "ref_hash_before": hash_of("st-ref-1"),
                    "adr_hash_before": hash_of("st-adr-1"),
                }
                # Change ONLY the ADR body; the reference doc's bytes are untouched.
                captured["pushed_commit"] = push_commit(
                    source, {"design/adr.md": DECISION_DOC_V2}, message="revise adr"
                )
                refresh = await client.post("/acme/refresh")
                captured["refresh_status"] = str(refresh.status_code)
                captured["refresh_commit"] = refresh.json()["commit"]
                after = (await client.get("/status")).json()["owners"]["acme"]
                captured["commit_after"] = after["served_commit"]
                captured["ref_hash_after"] = hash_of("st-ref-1")
                captured["adr_hash_after"] = hash_of("st-adr-1")
                return captured

    r = asyncio.run(scenario())

    # AC#3: served_commit advanced to exactly the pushed SHA (provenance/liveness).
    assert r["commit_after"] != r["commit_before"]
    assert r["commit_after"] == r["pushed_commit"]
    # /refresh still reports the landed commit under its own 'commit' key.
    assert r["refresh_status"] == "200"
    assert r["refresh_commit"] == r["pushed_commit"]
    # AC#4: the unchanged reference doc keeps its content_hash across the refresh.
    assert r["ref_hash_after"] == r["ref_hash_before"]
    # The doc whose bytes changed gets a different content_hash.
    assert r["adr_hash_after"] != r["adr_hash_before"]


def test_status_gated_by_bearer_token_while_healthz_stays_open(
    tmp_path: Path,
) -> None:
    # No lifespan is entered (TestClient used directly), so no clone runs; the
    # owner stays 'loading', which is all the auth gate needs to exercise.
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url="https://git.example.invalid/a.git")}),
        tmp_path / "cache",
        auth_token=NORTH_TOKEN,
    )
    client = TestClient(app)

    missing = client.get("/status")
    wrong = client.get("/status", headers={"Authorization": "Bearer not-the-token"})
    correct = client.get("/status", headers={"Authorization": f"Bearer {NORTH_TOKEN}"})
    health = client.get("/healthz")

    assert missing.status_code == 401  # no token -> rejected before the handler
    assert wrong.status_code == 401
    assert correct.status_code == 200
    assert set(correct.json()) == {"summary", "owners"}
    assert NORTH_TOKEN not in correct.text  # north token itself is never echoed back
    assert health.status_code == 200  # health check stays open with auth enabled
    assert health.text == "ok"


# The exact per-artifact field set the inventory contract promises.
ARTIFACT_KEYS = {
    "uri",
    "id",
    "type",
    "title",
    "summary",
    "path",
    "size",
    "content_hash",
}


def test_status_artifacts_true_returns_per_doc_metadata(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """``?artifacts=true`` turns each owner's docs into an actionable inventory.

    A bare ``knowledge://`` ref says nothing about what the artifact *is*; this
    asserts the fields that make it concrete — the repo-relative location, the
    type, and a summary — against ground truth taken from the fixture itself.
    """
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url=acme.url, ref=acme.ref)}),
        tmp_path / "cache",
    )

    body = asyncio.run(
        _get_status_ready(app, ("acme",), params={"artifacts": "true"})
    ).json()

    owner = body["owners"]["acme"]
    artifacts = owner["artifacts"]
    assert len(artifacts) == owner["docs_loaded"] == 2  # the un-exported README is out
    for artifact in artifacts:
        assert set(artifact) == ARTIFACT_KEYS
    by_id = {a["id"]: a for a in artifacts}

    # Paths are repo-relative to the checkout root: exactly the fixture's own keys,
    # so neither the absolute checkout prefix nor the cache dir layout leaks out.
    assert {a["path"] for a in artifacts} == {"docs/reference.md", "design/adr.md"}
    assert str(tmp_path) not in str(artifacts)

    reference = by_id["st-ref-1"]
    assert reference["uri"] == "knowledge://acme/reference-doc/st-ref-1"
    assert reference["path"] == "docs/reference.md"
    assert reference["type"] == "Reference Doc"  # the raw type, not the URI slug
    assert reference["title"] == "Status Reference"
    # summary is the doc's description — verbatim from the fixture frontmatter.
    assert reference["summary"] == "Reference served under the status tests."

    decision = by_id["st-adr-1"]
    assert decision["uri"] == "knowledge://acme/architecture-decision/st-adr-1"
    assert decision["path"] == "design/adr.md"
    assert decision["type"] == "Architecture Decision"
    # This fixture declares no description, so the summary is the derived one.
    assert decision["summary"] == "The status decision body."


def test_status_artifact_size_and_hash_describe_the_served_content(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """``size``/``content_hash`` measure the served body, not the on-disk file."""
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url=acme.url, ref=acme.ref)}),
        tmp_path / "cache",
    )

    body = asyncio.run(
        _get_status_ready(app, ("acme",), params={"artifacts": "true"})
    ).json()

    # The served docs are what read_resource hands a consumer; the inventory must
    # describe those exact strings.
    served = {d.id: d for d in app.state.owners["acme"].cache.docs}
    for artifact in body["owners"]["acme"]["artifacts"]:
        doc = served[artifact["id"]]
        assert artifact["size"] == len(doc.content)
        assert artifact["content_hash"] == doc.content_hash
    # Independent of the loader: the frontmatter block is excluded from both the
    # size and the served content it is taken over.
    reference = next(
        a for a in body["owners"]["acme"]["artifacts"] if a["id"] == "st-ref-1"
    )
    assert 0 < reference["size"] < len(REFERENCE_DOC)
    assert "export: true" not in served["st-ref-1"].content


def test_status_omits_artifacts_by_default_and_when_explicitly_false(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """The default payload is untouched — the inventory is strictly opt-in.

    Both clocks are injected so the three responses are byte-comparable; without
    that, ``last_pulled_age_seconds`` could tick between them.
    """
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    fixed_wall = datetime(2026, 7, 17, 7, 46, 46, tzinfo=timezone.utc)
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url=acme.url, ref=acme.ref)}),
        tmp_path / "cache",
        clock=FakeClock(),
        wall_clock=lambda: fixed_wall.timestamp(),
    )

    async def scenario() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                await asyncio.wait_for(
                    app.state.owners["acme"].ready.wait(), timeout=15
                )
                return (
                    await client.get("/status"),
                    await client.get("/status", params={"artifacts": "false"}),
                    await client.get("/status", params={"artifacts": "true"}),
                )

    default, explicit_false, opted_in = asyncio.run(scenario())

    assert default.status_code == explicit_false.status_code == 200
    # Byte-for-byte: opting out changes nothing about the pre-existing payload.
    assert default.text == explicit_false.text
    assert "artifacts" not in default.text
    assert "artifacts" not in explicit_false.json()["owners"]["acme"]
    # ...and the only difference under ?artifacts=true is the added key.
    opted_in_owner = opted_in.json()["owners"]["acme"]
    assert set(opted_in_owner) - set(default.json()["owners"]["acme"]) == {"artifacts"}


def test_status_artifacts_rejects_an_unsupported_value(tmp_path: Path) -> None:
    """A typo fails loudly rather than silently serving an inventory-free payload."""
    # No lifespan is entered, so no clone runs — the query parsing is all this needs.
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url="https://git.example.invalid/a.git")}),
        tmp_path / "cache",
    )
    client = TestClient(app)

    bad = client.get("/status", params={"artifacts": "1"})
    unset = client.get("/status")

    assert bad.status_code == 400
    assert "artifacts" in bad.json()["error"]
    assert unset.status_code == 200  # the param stays optional


def test_status_artifacts_is_an_empty_list_for_an_owner_with_no_docs(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed owner still carries the key, so the shape never varies by state."""
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    monkeypatch.setattr(
        owner_cache_module,
        "clone_owner",
        _failing_clone(BETA_URL, RuntimeError("boom")),
    )
    app = create_app(
        Registry(
            owners={
                "acme": OwnerSpec(url=acme.url, ref=acme.ref),
                "beta": OwnerSpec(url=BETA_URL, ref="release"),
            }
        ),
        tmp_path / "cache",
    )

    body = asyncio.run(
        _get_status_ready(app, ("acme", "beta"), params={"artifacts": "true"})
    ).json()

    beta = body["owners"]["beta"]
    assert beta["state"] == "failed"
    assert beta["artifacts"] == []  # present but empty, not missing
    assert len(body["owners"]["acme"]["artifacts"]) == 2


def test_status_artifacts_round_trip_through_yaml(
    make_bare_repo: Callable[..., GitRepoFixture],
    tmp_path: Path,
) -> None:
    """``?artifacts=`` composes with ``?format=``; both renderings agree."""
    acme = make_bare_repo(FIXTURE_FILES, ref="main")
    fixed_wall = datetime(2026, 7, 17, 7, 46, 46, tzinfo=timezone.utc)
    app = create_app(
        Registry(owners={"acme": OwnerSpec(url=acme.url, ref=acme.ref)}),
        tmp_path / "cache",
        clock=FakeClock(),
        wall_clock=lambda: fixed_wall.timestamp(),
    )

    async def scenario() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://gateway.test"
            ) as client:
                await asyncio.wait_for(
                    app.state.owners["acme"].ready.wait(), timeout=15
                )
                return (
                    await client.get("/status", params={"artifacts": "true"}),
                    await client.get(
                        "/status", params={"artifacts": "true", "format": "yaml"}
                    ),
                )

    json_resp, yaml_resp = asyncio.run(scenario())

    assert yaml_resp.status_code == 200
    assert yaml_resp.headers["content-type"].startswith("application/yaml")
    assert yaml.safe_load(yaml_resp.text) == json_resp.json()
    assert "docs/reference.md" in yaml_resp.text
