"""Real mTLS transport checks; the stub engine never calls a model/API."""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from tls_fixtures import CLIENT, OWNER, SERVER, Authority, delivered

from aelev_translation_provider import healthcheck
from aelev_translation_provider.app import create_app
from aelev_translation_provider.tls_identity import Identity
from aelev_translation_provider.tls_server import configured_server
from aelev_translation_provider.transport import Transport

PAYLOAD = {
    "schema_version": "1.0.0",
    "source_language": "en",
    "target_language": "ru",
    "text": "Hello",
}


class StubEngine:
    ready = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def translate(self, text: str, source: str, target: str) -> tuple[str, list[str]]:
        self.calls.append((text, source, target))
        return "Привет", ["MACHINE_TRANSLATION_UNVERIFIED"]


@pytest.fixture
def serving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Authority, int, StubEngine, Path]]:
    root = tmp_path.resolve()
    monkeypatch.setattr(healthcheck, "HEALTH_FILE", root / "readiness.json")
    authority = Authority(root / "issuer")
    identity_root = root / "server"
    delivered(identity_root, authority, *authority.leaf([SERVER]))
    identity = Identity(identity_root, OWNER)
    engine = StubEngine()
    with socket.socket() as temporary:
        temporary.bind(("127.0.0.1", 0))
        port = temporary.getsockname()[1]
    server = configured_server(
        create_app(engine, identity.available), identity, "127.0.0.1", port
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield authority, port, engine, identity_root
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def post(
    authority: Authority,
    port: int,
    client: tuple[Path, Path] | None,
    *,
    host: str = "localhost",
) -> dict[str, object]:
    context = ssl.create_default_context(cafile=authority.cert)
    if client is not None:
        context.load_cert_chain(*client)
    connection = http.client.HTTPSConnection(host, port, context=context, timeout=3)
    try:
        connection.request(
            "POST",
            "/v1/translate",
            json.dumps(PAYLOAD),
            {"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 200
        result: dict[str, object] = json.loads(response.read())
        return result
    finally:
        connection.close()


def test_real_mtls_preserves_exact_opaque_translation_contract(
    serving: tuple[Authority, int, StubEngine, Path],
) -> None:
    authority, port, engine, _ = serving
    assert post(authority, port, authority.leaf([CLIENT])) == {
        "schema_version": "1.0.0",
        "translated_text": "Привет",
        "warnings": ["MACHINE_TRANSLATION_UNVERIFIED"],
    }
    assert engine.calls == [("Hello", "en", "ru")]


def test_distinct_replica_keys_can_use_explicitly_allowed_workload_identity(
    serving: tuple[Authority, int, StubEngine, Path],
) -> None:
    authority, port, engine, _ = serving
    first, second = authority.leaf([CLIENT]), authority.leaf([CLIENT])
    assert first[1].read_bytes() != second[1].read_bytes()
    post(authority, port, first)
    post(authority, port, second)
    assert len(engine.calls) == 2


@pytest.mark.parametrize("kind", ["anonymous", "foreign", "hostname", "untrusted"])
def test_unauthorized_connection_never_dispatches_translation(
    serving: tuple[Authority, int, StubEngine, Path], tmp_path: Path, kind: str
) -> None:
    authority, port, engine, _ = serving
    client = None if kind == "anonymous" else authority.leaf([CLIENT])
    if kind == "foreign":
        client = authority.leaf([SERVER])
    if kind == "untrusted":
        client = Authority(tmp_path.resolve() / "untrusted").leaf([CLIENT])
    with pytest.raises((OSError, http.client.HTTPException)):
        post(
            authority,
            port,
            client,
            host="127.0.0.1" if kind == "hostname" else "localhost",
        )
    assert engine.calls == []


def test_local_readiness_tracks_identity_withdrawal_without_api_call(
    serving: tuple[Authority, int, StubEngine, Path],
) -> None:
    _, _, engine, root = serving
    deadline = time.monotonic() + 3
    while not healthcheck.healthy() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert healthcheck.healthy()
    marker = json.loads((root / "current.json").read_text())
    marker["state"] = "UNAVAILABLE"
    (root / "current.json").write_text(json.dumps(marker))
    deadline = time.monotonic() + 3
    while healthcheck.healthy() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not healthcheck.healthy()
    assert engine.calls == []


def test_network_listener_requires_explicit_complete_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    monkeypatch.setenv("AELEV_TRANSLATION_PROVIDER_TLS_ROOT", str(root))
    assert Transport.environment().mode == "uds"
    (root / "identity.json").write_text("{}")
    with pytest.raises(RuntimeError, match="PROVIDER_TRANSPORT_CONFIG_INVALID"):
        Transport.environment()
    config = {
        "schema_version": 1,
        "transport": "mtls",
        "listen_host": "0.0.0.0",
        "listen_port": 18487,
    }
    path = root / "transport.json"
    path.write_text(json.dumps(config))
    assert Transport.environment() == Transport("mtls", root)
    for field, value in (
        ("transport", "http"),
        ("listen_port", True),
        ("listen_port", 0),
        ("listen_host", "https://other"),
        ("schema_version", True),
        ("model", "not-transport-configuration"),
    ):
        path.write_text(json.dumps({**config, field: value}))
        with pytest.raises(RuntimeError, match="PROVIDER_TRANSPORT_CONFIG_INVALID"):
            Transport.environment()
    path.unlink()
    path.symlink_to(root / "missing.json")
    with pytest.raises(RuntimeError, match="PROVIDER_TRANSPORT_CONFIG_INVALID"):
        Transport.environment()
