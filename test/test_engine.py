"""Opaque contract, artifact integrity and bounded provider behavior."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import httpx
import pytest
import uvicorn

from aelev_translation_provider import engine
from aelev_translation_provider.app import create_app
from aelev_translation_provider.contract import (
    ProviderRequestError,
    parse_request,
    serialize_success,
)
from aelev_translation_provider.languages import LANGUAGES, language_name

ROOT = Path(__file__).resolve().parents[1]


def settings(tmp_path: Path | None = None) -> engine.Settings:
    lock_path = ROOT / "provider.lock.json"
    reference, artifacts = engine.read_provider_lock(lock_path)
    return engine.Settings(
        model_root=tmp_path or Path("/model"),
        lock_path=lock_path,
        socket_path=Path("/socket"),
        runtime_path=Path("/runtime"),
        execution_ref=reference,
        artifacts=artifacts,
    )


def test_lock_and_docker_recipe_pin_the_same_release() -> None:
    lock = json.loads((ROOT / "provider.lock.json").read_text())
    recipe = (ROOT / "Dockerfile").read_text()
    reference, artifacts = engine.read_provider_lock(ROOT / "provider.lock.json")
    assert lock["declared_language_count"] == len(LANGUAGES) == 150
    assert lock["runtime"]["source_sha256"] in recipe
    assert lock["runtime"]["revision"] in recipe
    assert reference == lock["execution_ref"]
    assert set(artifacts) == {engine.MODEL_FILE}
    assert "translator_service" not in recipe
    assert "Index-Translate-Apache-2.0.txt" in recipe
    assert "llama.cpp-MIT.txt" in recipe


@pytest.mark.parametrize(
    "mutation",
    ["status", "path", "sha256", "size", "ref", "thinking", "context", "files"],
)
def test_bad_lock_fails_closed(tmp_path: Path, mutation: str) -> None:
    lock = json.loads((ROOT / "provider.lock.json").read_text())
    if mutation == "status":
        lock["status"] = "CANDIDATE"
    elif mutation in {"path", "sha256", "size"}:
        lock["files"][0][mutation] = {
            "path": "../other.gguf",
            "sha256": "g" * 64,
            "size": True,
        }[mutation]
    elif mutation == "ref":
        lock["execution_ref"] = "other"
    elif mutation == "thinking":
        lock["runtime"]["enable_thinking"] = True
    elif mutation == "context":
        lock["runtime"]["context_size"] = 1024
    else:
        lock["files"] *= 2
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(RuntimeError):
        engine.read_provider_lock(path)


def test_artifact_requires_exact_regular_file(tmp_path: Path) -> None:
    content = b"verified fixture"
    lock = json.loads((ROOT / "provider.lock.json").read_text())
    lock["files"][0].update(
        sha256=hashlib.sha256(content).hexdigest(), size=len(content)
    )
    lock["execution_ref"] = engine.execution_reference(
        lock["files"][0]["sha256"], lock["runtime"]
    )
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    reference, artifacts = engine.read_provider_lock(path)
    configured = engine.Settings(
        tmp_path,
        path,
        Path("/socket"),
        Path("/runtime"),
        reference,
        artifacts,
    )
    artifact = tmp_path / engine.MODEL_FILE
    artifact.write_bytes(content)
    engine.verify_model_artifacts(configured)
    artifact.write_bytes(b"x" * len(content))
    with pytest.raises(RuntimeError, match="DIGEST"):
        engine.verify_model_artifacts(configured)
    artifact.unlink()
    artifact.symlink_to(path)
    with pytest.raises(RuntimeError, match="SIZE"):
        engine.verify_model_artifacts(configured)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "schema_version": "2.0.0",
            "source_language": "en",
            "target_language": "de",
            "text": "x",
        },
        {
            "schema_version": "1.0.0",
            "source_language": "en",
            "target_language": "de",
            "text": "x",
            "model": "forbidden",
        },
        {
            "schema_version": "1.0.0",
            "source_language": "EN",
            "target_language": "de",
            "text": "x",
        },
        {
            "schema_version": "1.0.0",
            "source_language": "en",
            "target_language": "de",
            "text": " ",
        },
    ],
)
def test_contract_rejects_every_non_opaque_shape(payload: object) -> None:
    with pytest.raises(ProviderRequestError, match="TRANSLATOR_REQUEST_INVALID"):
        parse_request(payload)


def test_contract_schema_and_serializer_are_exact() -> None:
    schema = json.loads((ROOT / "contracts/opaque-translation-v1.json").read_text())
    request = schema["$defs"]["request"]
    success = schema["$defs"]["success"]
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {
        "schema_version",
        "source_language",
        "target_language",
        "text",
    }
    assert success["additionalProperties"] is False
    assert serialize_success("Hallo", ["MACHINE_TRANSLATION_UNVERIFIED"]) == {
        "schema_version": "1.0.0",
        "translated_text": "Hallo",
        "warnings": ["MACHINE_TRANSLATION_UNVERIFIED"],
    }
    with pytest.raises(RuntimeError, match="PROVIDER_RESPONSE_INVALID"):
        serialize_success("", [])
    with pytest.raises(RuntimeError, match="PROVIDER_RESPONSE_INVALID"):
        serialize_success("valid", ["duplicate", "duplicate"])


def test_language_inventory_rejects_unknown_values() -> None:
    assert language_name("en", source=True) == "英语"
    with pytest.raises(ProviderRequestError, match="UNSUPPORTED_TARGET"):
        language_name("xx")


class FakeEngine:
    ready = True

    def translate(self, text: str, source: str, target: str) -> tuple[str, list[str]]:
        assert (text, source, target) == ("Hello", "en", "de")
        return "Hallo", ["MACHINE_TRANSLATION_UNVERIFIED"]


async def asgi_request(
    app: Any, method: str, path: str, payload: object | None = None
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://provider"
    ) as client:
        return await client.request(method, path, json=payload)


def test_http_response_discloses_no_implementation_identity() -> None:
    app = create_app(FakeEngine())
    response = asyncio.run(
        asgi_request(
            app,
            "POST",
            "/v1/translate",
            {
                "schema_version": "1.0.0",
                "source_language": "en",
                "target_language": "de",
                "text": "Hello",
            },
        )
    )
    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "1.0.0",
        "translated_text": "Hallo",
        "warnings": ["MACHINE_TRANSLATION_UNVERIFIED"],
    }
    assert asyncio.run(asgi_request(app, "GET", "/healthz")).json() == {"status": "ok"}


def test_health_is_provider_runtime_readiness() -> None:
    unavailable = cast(Any, FakeEngine())
    unavailable.ready = False
    response = asyncio.run(asgi_request(create_app(unavailable), "GET", "/healthz"))
    assert response.status_code == 503


def test_real_unix_socket_round_trip() -> None:
    socket_path = Path("/tmp") / f"aelev-provider-{os.getpid()}-{uuid.uuid4().hex}.sock"
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(FakeEngine()),
            uds=str(socket_path),
            access_log=False,
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not socket_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert socket_path.exists()
        transport = httpx.HTTPTransport(uds=str(socket_path))
        with httpx.Client(transport=transport, base_url="http://provider") as client:
            response = client.post(
                "/v1/translate",
                json={
                    "schema_version": "1.0.0",
                    "source_language": "en",
                    "target_language": "de",
                    "text": "Hello",
                },
            )
        assert response.status_code == 200
        assert response.json()["translated_text"] == "Hallo"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        socket_path.unlink(missing_ok=True)
        assert not thread.is_alive()


def test_control_tokens_and_empty_output_are_bounded_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = settings()

    def no_verify(_: engine.Settings) -> None:
        pass

    def no_start(
        _: engine.TranslationEngine, timeout_seconds: float | None = None
    ) -> None:
        del timeout_seconds

    monkeypatch.setattr(engine, "verify_model_artifacts", no_verify)
    monkeypatch.setattr(engine.TranslationEngine, "_start_runtime", no_start)
    provider = engine.TranslationEngine(configured)
    provider._runtime_loaded = True  # pyright: ignore[reportPrivateUsage]
    provider._process = cast(  # pyright: ignore[reportPrivateUsage]
        Any, SimpleNamespace(poll=lambda: None)
    )
    monkeypatch.setattr(
        provider,
        "_post",
        Mock(
            side_effect=[
                {"tokens": [1]},
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "<think>secret"},
                        }
                    ]
                },
                {"tokens": [1]},
                {"choices": [{"finish_reason": "stop", "message": {"content": " "}}]},
            ]
        ),
    )
    with pytest.raises(ProviderRequestError, match="CONTROL_TOKEN"):
        provider.translate("hello", "en", "de")
    with pytest.raises(ProviderRequestError, match="EMPTY_OUTPUT"):
        provider.translate("other", "en", "de")
    provider._process = None  # pyright: ignore[reportPrivateUsage]
    provider.close()
