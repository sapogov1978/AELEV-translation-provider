"""Real TLS verifies peer scope, certificate renewal and CA replacement."""

from __future__ import annotations

import gc
import http.client
import json
import socket
import ssl
import subprocess
import threading
import time
import weakref
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from tls_fixtures import CLIENT, OWNER, SERVER, Authority, delivered, openssl

from aelev_translation_provider.tls_identity import Identity, IdentityError
from aelev_translation_provider.tls_server import configured_server


@pytest.fixture
def authority(tmp_path: Path) -> Authority:
    return Authority(tmp_path / "issuer")


def test_delivered_leaf_is_independently_verified_and_rotates(
    tmp_path: Path, authority: Authority
) -> None:
    root = tmp_path / "identity"
    cert, key = authority.leaf([SERVER])
    delivered(root, authority, cert, key)
    identity = Identity(root, OWNER)
    context = identity.current()
    replacement = authority.leaf([SERVER])
    delivered(root, authority, *replacement)
    assert identity.current() is not context
    marker = json.loads((root / "current.json").read_text())
    marker["updated_at"] = (datetime.now(UTC) - timedelta(seconds=21)).isoformat()
    (root / "current.json").write_text(json.dumps(marker))
    assert not identity.available()


@pytest.mark.parametrize("names", [[], [CLIENT], [SERVER, CLIENT]])
def test_same_ca_wrong_missing_or_multiple_uris_are_not_owned_identity(
    tmp_path: Path, authority: Authority, names: list[str]
) -> None:
    root = tmp_path / "identity"
    delivered(root, authority, *authority.leaf(names))
    assert not Identity(root, OWNER).available()


def test_metadata_cannot_hide_wrong_issuer_expiry_or_byte_changes(
    tmp_path: Path, authority: Authority
) -> None:
    root = tmp_path / "identity"
    expired = authority.leaf([SERVER], expired=True)
    delivered(root, authority, *expired)
    assert not Identity(root, OWNER).available()
    other = Authority(tmp_path / "other")
    delivered(root, authority, *other.leaf([SERVER]))
    assert not Identity(root, OWNER).available()
    delivered(root, authority, *authority.leaf([SERVER]))
    identity = Identity(root, OWNER)
    identity.current()
    marker = json.loads((root / "current.json").read_text())
    (root / "generations" / marker["generation"] / "tls.pem").write_bytes(b"changed")
    assert not identity.available()


def test_policy_and_pointer_cannot_expand_scope_or_fall_back_to_pem(
    tmp_path: Path, authority: Authority
) -> None:
    root = tmp_path / "identity"
    delivered(root, authority, *authority.leaf([SERVER]))
    identity = Identity(root, OWNER)
    identity.current()
    (root / "current.json").unlink()
    assert not identity.available()
    with pytest.raises(IdentityError):
        identity.current()
    (root / "identity.json").write_text("{}")
    assert not identity.available()


@pytest.fixture
def running(
    tmp_path: Path, authority: Authority
) -> Iterator[tuple[Path, int, list[str]]]:
    root = tmp_path / "server"
    delivered(root, authority, *authority.leaf([SERVER]))
    app = FastAPI()
    calls: list[str] = []

    @app.get("/v1/status")
    def status() -> dict[str, str]:
        calls.append("status")
        return {"state": "READY"}

    @app.post("/v1/infer")
    def infer() -> dict[str, str]:
        calls.append("infer")
        return {"outcome": "REVIEW"}

    with socket.socket() as temporary:
        temporary.bind(("127.0.0.1", 0))
        port = temporary.getsockname()[1]
    server = configured_server(app, Identity(root, OWNER), "127.0.0.1", port)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        yield root, port, calls
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def request(
    port: int,
    authority: Authority,
    cert: Path,
    key: Path,
    *,
    infer: bool = False,
    no_sni: bool = False,
) -> int:
    context = ssl.create_default_context(cafile=authority.cert)
    context.load_cert_chain(cert, key)
    if no_sni:
        context.check_hostname = False
    connection = http.client.HTTPSConnection(
        "127.0.0.1" if no_sni else "localhost", port, context=context, timeout=3
    )
    try:
        connection.request(
            "POST" if infer else "GET",
            "/v1/infer" if infer else "/v1/status",
            body=b'{"input":"must-not-dispatch"}' if infer else None,
        )
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def test_real_tls_admits_exact_client_and_denies_same_ca_foreign_identity(
    authority: Authority, running: tuple[Path, int, list[str]]
) -> None:
    _, port, calls = running
    assert request(port, authority, *authority.leaf([CLIENT])) == 200
    assert calls == ["status"]
    for names in ([SERVER], [], [CLIENT, SERVER]):
        with pytest.raises((OSError, http.client.HTTPException)):
            request(port, authority, *authority.leaf(names), infer=True)
    assert calls == ["status"]


def test_a_ca_certificate_cannot_impersonate_the_exact_workload(
    authority: Authority, running: tuple[Path, int, list[str]]
) -> None:
    _, port, calls = running
    with pytest.raises((OSError, http.client.HTTPException)):
        request(port, authority, *authority.leaf([CLIENT], is_ca=True), infer=True)
    assert calls == []


def test_encrypted_key_is_rejected_without_interactive_password_input(
    tmp_path: Path, authority: Authority
) -> None:
    cert, key = authority.leaf([SERVER])
    encrypted = tmp_path / "encrypted.key"
    openssl(
        "pkcs8",
        "-topk8",
        "-in",
        str(key),
        "-out",
        str(encrypted),
        "-passout",
        "pass:ephemeral-test-only",
    )
    root = tmp_path / "identity"
    delivered(root, authority, cert, encrypted)
    assert not Identity(root, OWNER).available()


def test_no_sni_still_requires_exact_client_identity(
    authority: Authority, running: tuple[Path, int, list[str]]
) -> None:
    _, port, calls = running
    assert request(port, authority, *authority.leaf([CLIENT]), no_sni=True) == 200
    with pytest.raises((OSError, http.client.HTTPException)):
        request(port, authority, *authority.leaf([SERVER]), no_sni=True, infer=True)
    assert calls == ["status"]


def test_existing_connection_does_not_dispatch_after_identity_withdrawal(
    authority: Authority, running: tuple[Path, int, list[str]]
) -> None:
    root, port, calls = running
    context = ssl.create_default_context(cafile=authority.cert)
    context.load_cert_chain(*authority.leaf([CLIENT]))
    connection = http.client.HTTPSConnection(
        "localhost", port, context=context, timeout=3
    )
    try:
        connection.request("GET", "/v1/status")
        first = connection.getresponse()
        first.read()
        assert first.status == 200
        marker = json.loads((root / "current.json").read_text())
        marker["state"] = "UNAVAILABLE"
        (root / "current.json").write_text(json.dumps(marker))
        connection.request("POST", "/v1/infer", body=b"{}")
        blocked = connection.getresponse()
        assert blocked.status == 503
        assert json.loads(blocked.read()) == {
            "detail": "PROVIDER_TLS_IDENTITY_UNAVAILABLE"
        }
        assert calls == ["status"]
    finally:
        connection.close()


def test_client_identity_is_verified_for_its_actual_tls_role(
    tmp_path: Path, authority: Authority
) -> None:
    root = tmp_path / "client"
    delivered(root, authority, *authority.leaf([CLIENT]), own=CLIENT)
    context = Identity(root, OWNER, "client").current()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_existing_connection_cannot_outlive_replacement_of_its_ca(
    tmp_path: Path, authority: Authority, running: tuple[Path, int, list[str]]
) -> None:
    root, port, calls = running
    context = ssl.create_default_context(cafile=authority.cert)
    context.load_cert_chain(*authority.leaf([CLIENT]))
    connection = http.client.HTTPSConnection(
        "localhost", port, context=context, timeout=3
    )
    try:
        connection.request("GET", "/v1/status")
        first = connection.getresponse()
        first.read()
        assert first.status == 200
        replacement = Authority(tmp_path / "replacement-authority")
        delivered(root, replacement, *replacement.leaf([SERVER]))
        connection.request("POST", "/v1/infer", body=b"{}")
        blocked = connection.getresponse()
        assert blocked.status == 503
        assert json.loads(blocked.read()) == {
            "detail": "PROVIDER_TLS_IDENTITY_UNAVAILABLE"
        }
        assert calls == ["status"]
        assert request(port, replacement, *replacement.leaf([CLIENT])) == 200
        assert calls == ["status", "status"]
    finally:
        connection.close()


def test_real_tls_renews_leaf_and_replaces_ca_without_listener_restart(
    tmp_path: Path, authority: Authority, running: tuple[Path, int, list[str]]
) -> None:
    root, port, calls = running
    old_client = authority.leaf([CLIENT])
    assert request(port, authority, *old_client) == 200
    delivered(root, authority, *authority.leaf([SERVER]))
    assert request(port, authority, *old_client) == 200
    new = Authority(tmp_path / "new-authority")
    delivered(root, new, *new.leaf([SERVER]))
    with pytest.raises((OSError, http.client.HTTPException)):
        request(port, authority, *old_client)
    assert request(port, new, *new.leaf([CLIENT])) == 200
    assert calls == ["status"] * 3


def test_fresh_context_cannot_use_last_good_generation_after_withdrawal(
    authority: Authority, running: tuple[Path, int, list[str]]
) -> None:
    root, port, calls = running
    client = authority.leaf([CLIENT])
    assert request(port, authority, *client) == 200
    marker = json.loads((root / "current.json").read_text())
    marker["state"] = "UNAVAILABLE"
    (root / "current.json").write_text(json.dumps(marker))
    with pytest.raises((OSError, http.client.HTTPException)):
        request(port, authority, *client)
    assert calls == ["status"]


def test_callback_context_survives_hrr_gc_and_identity_renewal(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    authority: Authority,
) -> None:
    """Exercise the second ClientHello of CVE-2026-19445 on Python 3.13.7."""
    original_factory = Identity.wire_context
    callbacks: list[str | None] = []
    references: list[weakref.ReferenceType[ssl.SSLContext]] = []

    def selecting(self: Identity) -> ssl.SSLContext:
        initial = original_factory(self)
        initial.set_ecdh_curve("prime256v1")
        original = initial.sni_callback
        assert original is not None
        references.append(weakref.ref(initial))

        def collect_and_select(
            channel: ssl.SSLObject,
            hostname: str,
            context: ssl.SSLContext,
        ) -> int | None:
            gc.collect()
            callbacks.append(hostname)
            # X25519 is the client's first share; requiring P-256 provokes
            # a real TLS 1.3 HelloRetryRequest and another ClientHello.
            self.current().set_ecdh_curve("prime256v1")
            result = original(channel, hostname, context)
            gc.collect()
            return result

        initial.sni_callback = collect_and_select
        return initial

    monkeypatch.setattr(Identity, "wire_context", selecting)
    root, port, calls = cast(
        tuple[Path, int, list[str]], request.getfixturevalue("running")
    )
    cert, key = authority.leaf([CLIENT])
    for attempt in range(2):
        if attempt:
            delivered(root, authority, *authority.leaf([SERVER]))
        result = subprocess.run(
            [
                "openssl",
                "s_client",
                "-connect",
                f"localhost:{port}",
                "-servername",
                "localhost",
                "-CAfile",
                str(authority.cert),
                "-cert",
                str(cert),
                "-key",
                str(key),
                "-groups",
                "X25519:P-256",
                "-tls1_3",
                "-quiet",
                "-msg",
            ],
            input=(
                "GET /v1/status HTTP/1.1\r\nHost: localhost\r\n"
                "Connection: close\r\n\r\n"
            ),
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        assert "200 OK" in result.stdout and '{"state":"READY"}' in result.stdout
        gc.collect()
        assert (
            "cf21ad74e59a6111be1d8c021e65b891c2a211167abb8c5e079e09e2c8a8339c"
            in "".join(result.stdout.lower().split())
        )
        assert len(callbacks) >= attempt + 1
        assert references[0]() is not None
    assert calls == ["status", "status"]
