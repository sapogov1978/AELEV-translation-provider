"""Opaque contract and bounded remote-provider behavior."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, cast

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
from aelev_translation_provider.languages import language_name

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"


def settings(api_key: str = "fixture-openai-key-not-secret") -> engine.Settings:
    lock_path = ROOT / "provider.lock.json"
    return engine.Settings(
        lock_path=lock_path,
        prompt_root=PROMPTS,
        socket_path=Path("/socket"),
        profile=engine.read_provider_lock(lock_path, PROMPTS),
        api_key=api_key,
    )


def openai_response(translated: str = "Hallo") -> dict[str, object]:
    return {
        "status": "completed",
        "model": "gpt-6.1-sol",
        "output": [
            {"type": "reasoning", "id": "rs_fixture", "summary": []},
            {
                "type": "message",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {"translated_text": translated}, ensure_ascii=False
                        ),
                    }
                ],
            },
        ],
    }


def api_response(translated: str = "Hallo") -> httpx.Response:
    return httpx.Response(200, json=openai_response(translated))


def test_lock_prompt_and_docker_pin_remote_profile() -> None:
    lock = json.loads((ROOT / "provider.lock.json").read_text())
    recipe = (ROOT / "Dockerfile").read_text()
    profile = engine.read_provider_lock(ROOT / "provider.lock.json", PROMPTS)
    assert profile.model == lock["api"]["model"] == "gpt-6.1-sol"
    assert profile.endpoint == "https://api.openai.com/v1/responses"
    assert profile.execution_ref == lock["execution_ref"]
    assert lock["api"]["store"] is False
    assert "llama.cpp" not in recipe
    assert ".gguf" not in recipe
    assert "download-model" not in recipe
    assert "OPENAI_API_KEY=" not in recipe
    assert "verify-config" in recipe


@pytest.mark.parametrize(
    "mutation",
    ["status", "provider", "endpoint", "model", "store", "prompt", "transport", "ref"],
)
def test_bad_lock_fails_closed(tmp_path: Path, mutation: str) -> None:
    lock = json.loads((ROOT / "provider.lock.json").read_text())
    if mutation == "status":
        lock["status"] = "CANDIDATE"
    elif mutation == "provider":
        lock["provider"] = "other"
    elif mutation == "endpoint":
        lock["api"]["endpoint"] = "https://example.invalid/v1/responses"
    elif mutation == "model":
        lock["api"]["model"] = "other"
    elif mutation == "store":
        lock["api"]["store"] = True
    elif mutation == "prompt":
        lock["api"]["prompt_sha256"] = "0" * 64
    elif mutation == "transport":
        lock["transport"]["mode"] = "public-egress-gateway-v1"
    else:
        lock["execution_ref"] = "other"
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(RuntimeError):
        engine.read_provider_lock(path, PROMPTS)


def test_prompt_digest_detects_changed_prompt(tmp_path: Path) -> None:
    prompt_root = tmp_path / "prompts"
    prompt_root.mkdir()
    prompt = prompt_root / "domain-preserving-translation-v1.txt"
    prompt.write_text("changed")
    with pytest.raises(RuntimeError, match="PROMPT_DIGEST"):
        engine.read_provider_lock(ROOT / "provider.lock.json", prompt_root)


def test_placeholder_key_is_never_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    environment = {
        "AELEV_TRANSLATION_PROVIDER_LOCK_PATH": str(ROOT / "provider.lock.json"),
        "AELEV_TRANSLATION_PROVIDER_PROMPT_ROOT": str(PROMPTS),
        "AELEV_TRANSLATION_PROVIDER_SOCKET_PATH": str(tmp_path / "provider.sock"),
        "OPENAI_API_KEY_FILE": "",
        "OPENAI_API_KEY": "REPLACE_WITH_OPENAI_API_KEY",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="CREDENTIAL_UNREADABLE"):
        engine.Settings.from_environment()
    assert "fixture-openai-key-not-secret" not in repr(settings())


def test_ignored_dotenv_file_supplies_runtime_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    credential = tmp_path / "credential.env"
    credential.write_text("OPENAI_API_KEY=fixture-openai-key-not-secret\n")
    monkeypatch.setenv(
        "AELEV_TRANSLATION_PROVIDER_LOCK_PATH", str(ROOT / "provider.lock.json")
    )
    monkeypatch.setenv("AELEV_TRANSLATION_PROVIDER_PROMPT_ROOT", str(PROMPTS))
    monkeypatch.setenv(
        "AELEV_TRANSLATION_PROVIDER_SOCKET_PATH", str(tmp_path / "provider.sock")
    )
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(credential))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert engine.Settings.from_environment().api_key == "fixture-openai-key-not-secret"


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


def test_language_inventory_rejects_unknown_values() -> None:
    assert language_name("en", source=True) == "English"
    with pytest.raises(ProviderRequestError, match="UNSUPPORTED_TARGET"):
        language_name("xx")


def test_remote_request_preserves_domain_context_and_uses_api() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.openai.com/v1/responses"
        requests.append(request)
        assert (
            request.headers["Authorization"] == "Bearer fixture-openai-key-not-secret"
        )
        api = json.loads(request.content)
        assert api["model"] == "gpt-6.1-sol"
        assert api["store"] is False
        assert api["reasoning"] == {"effort": "medium"}
        assert api["text"]["format"]["type"] == "json_schema"
        assert "infer the subject domain" in api["instructions"]
        model_input = json.loads(api["input"][0]["content"][0]["text"])
        assert model_input == {
            "source_language": {"code": "en", "name": "English"},
            "target_language": {"code": "de", "name": "German"},
            "source_text": "The kinase assay uses a 5 µM ATP concentration.",
        }
        return api_response("Der Kinase-Assay verwendet 5 µM ATP.")

    provider = engine.TranslationEngine(
        settings(), transport=httpx.MockTransport(respond)
    )
    try:
        expected = (
            "Der Kinase-Assay verwendet 5 µM ATP.",
            ["MACHINE_TRANSLATION_UNVERIFIED"],
        )
        assert (
            provider.translate(
                "The kinase assay uses a 5 µM ATP concentration.", "en", "de"
            )
            == expected
        )
        assert (
            provider.translate(
                "The kinase assay uses a 5 µM ATP concentration.", "en", "de"
            )
            == expected
        )
        assert len(requests) == 1
    finally:
        provider.close()


def test_api_rejection_is_bounded_provider_failure() -> None:
    def reject(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "invalid_api_key"}})

    provider = engine.TranslationEngine(
        settings(), transport=httpx.MockTransport(reject)
    )
    try:
        with pytest.raises(engine.ProviderUnavailable, match="RUNTIME_UNAVAILABLE"):
            provider.translate("Hello", "en", "de")
    finally:
        provider.close()


@pytest.mark.parametrize("translated", ["", "<think>secret"])
def test_invalid_model_output_is_bounded(translated: str) -> None:
    provider = engine.TranslationEngine(
        settings(),
        transport=httpx.MockTransport(lambda _: api_response(translated)),
    )
    try:
        with pytest.raises(ProviderRequestError):
            provider.translate("Hello", "en", "de")
    finally:
        provider.close()


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
    assert "openai" not in response.text.casefold()
    assert "gpt" not in response.text.casefold()


def test_health_is_local_provider_readiness() -> None:
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
