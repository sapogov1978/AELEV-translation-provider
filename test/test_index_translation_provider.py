"""Selected provider: artifact integrity, language boundaries and full outputs."""

import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from translator_service import index_translation_provider as provider
from translator_service.index_languages import LANGUAGES, language_name
from translator_service.protocol import (
    EvidenceTranslationRequest,
    ProfileLocalizationRequest,
)

ROOT = Path(__file__).resolve().parents[1]


def noop(_: object) -> None:
    pass


@pytest.fixture
def settings() -> provider.TranslationSettings:
    path = ROOT / "translator.lock.json"
    ref, artifacts = provider.read_translator_lock(path)
    return provider.TranslationSettings(
        Path("/model"), path, Path("/socket"), ref, artifacts, 1
    )


@pytest.fixture
def engine(
    monkeypatch: pytest.MonkeyPatch, settings: provider.TranslationSettings
) -> provider.TranslationEngine:
    monkeypatch.setattr(provider, "verify_model_artifacts", noop)
    monkeypatch.setattr(provider.TranslationEngine, "_start_runtime", noop)
    item = provider.TranslationEngine(settings)
    item._runtime_loaded = True  # pyright: ignore[reportPrivateUsage]
    item._process = Mock(poll=Mock(return_value=None))  # pyright: ignore[reportPrivateUsage]
    return item


def request(
    engine: provider.TranslationEngine,
    value: str = "source",
    source: str = "en",
    target: str = "de",
) -> EvidenceTranslationRequest:
    return EvidenceTranslationRequest(
        engine.translator_ref,
        source,
        target,
        "sha256:" + hashlib.sha256(value.encode()).hexdigest(),
        value,
    )


def response(content: str, finish: str = "stop") -> dict[str, object]:
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}]}


def install_native(
    monkeypatch: pytest.MonkeyPatch,
    outputs: list[dict[str, object]],
    calls: list[dict[str, object]],
) -> None:
    def post(
        self: provider.TranslationEngine,
        route: str,
        payload: dict[str, object],
        deadline: float,
    ) -> dict[str, object]:
        del self, deadline
        if route == "/tokenize":
            return {"tokens": [1]}
        assert route == "/v1/chat/completions"
        calls.append(payload)
        return outputs.pop(0)

    monkeypatch.setattr(provider.TranslationEngine, "_post", post)


def test_selected_lock_and_build_pins_agree(
    settings: provider.TranslationSettings,
) -> None:
    lock = json.loads(settings.lock_path.read_text())
    recipe = (ROOT / "Dockerfile").read_text()
    assert lock["declared_language_count"] == len(LANGUAGES) == 150
    assert lock["runtime"]["source_sha256"] in recipe
    assert lock["runtime"]["revision"] in recipe
    assert "COPY translator.lock.json download-model.py /supply/" in recipe
    assert "--lock /supply/translator.lock.json" in recipe
    assert all(name in recipe for name in settings.artifacts)
    assert "rust:" not in recipe and "madlad400" not in recipe
    assert settings.translator_ref.startswith("IndexTeam/Index-Translate-9B-q4km@")


def test_batches_yield_to_waiting_request_in_fifo_order(
    monkeypatch: pytest.MonkeyPatch, engine: provider.TranslationEngine
) -> None:
    first = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    failures: list[Exception] = []

    def unit(
        self: provider.TranslationEngine,
        value: str,
        source: str,
        target: str,
        budget: int,
        deadline: float,
    ) -> str:
        del self, source, target, budget, deadline
        calls.append(value)
        if value == "first":
            first.set()
            assert release.wait(2)
        return value

    def translate(values: list[str]) -> None:
        try:
            engine._translate(values, source="en", target="de")  # pyright: ignore[reportPrivateUsage]
        except Exception as error:
            failures.append(error)

    monkeypatch.setattr(provider.TranslationEngine, "_unit", unit)
    bulk = threading.Thread(target=translate, args=(["first", "second"],))
    urgent = threading.Thread(target=translate, args=(["urgent"],))
    bulk.start()
    try:
        assert first.wait(2)
        urgent.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with engine._condition:  # pyright: ignore[reportPrivateUsage]
                if len(engine._tickets) == 2:  # pyright: ignore[reportPrivateUsage]
                    break
            time.sleep(0.01)
        else:
            raise AssertionError("second request never entered FIFO")
    finally:
        release.set()
        bulk.join(3)
        if urgent.ident is not None:
            urgent.join(3)
    assert not bulk.is_alive() and not urgent.is_alive() and not failures
    assert calls == ["first", "urgent", "second"]


@pytest.mark.parametrize(
    "mutation",
    ["status", "path", "sha256", "size", "ref", "thinking", "context", "files", "seed"],
)
def test_bad_lock_fails_closed(tmp_path: Path, mutation: str) -> None:
    lock = json.loads((ROOT / "translator.lock.json").read_text())
    if mutation == "status":
        lock["status"] = "CANDIDATE"
    elif mutation in {"path", "sha256", "size"}:
        lock["files"][0][mutation] = {
            "path": "../other.gguf",
            "sha256": "g" * 64,
            "size": True,
        }[mutation]
    elif mutation == "ref":
        lock["translator_ref"] = "other"
    elif mutation == "thinking":
        lock["runtime"]["enable_thinking"] = True
    elif mutation == "context":
        lock["runtime"]["context_size"] = 1024
    elif mutation == "seed":
        lock["runtime"]["seed"] += 1
    else:
        lock["files"] *= 2
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    with pytest.raises(RuntimeError):
        provider.read_translator_lock(path)


def test_artifact_checks_hash_size_and_symlink(tmp_path: Path) -> None:
    value = b"verified fixture"
    name = "Index-Translate-9B.Q4_K_M.gguf"
    checksum = hashlib.sha256(value).hexdigest()
    lock = json.loads((ROOT / "translator.lock.json").read_text())
    lock["files"][0].update(sha256=checksum, size=len(value))
    lock["translator_ref"] = provider.translator_reference(checksum, lock["runtime"])
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    ref, artifacts = provider.read_translator_lock(path)
    settings = provider.TranslationSettings(
        tmp_path, path, Path("/socket"), ref, artifacts, 1
    )
    artifact = tmp_path / name
    artifact.write_bytes(value)
    provider.verify_model_artifacts(settings)
    artifact.write_bytes(b"x" * len(value))
    with pytest.raises(RuntimeError, match="verification"):
        provider.verify_model_artifacts(settings)
    artifact.write_bytes(b"x")
    with pytest.raises(RuntimeError, match="size"):
        provider.verify_model_artifacts(settings)
    artifact.unlink()
    artifact.symlink_to(path)
    with pytest.raises(RuntimeError, match="size or type"):
        provider.verify_model_artifacts(settings)


@pytest.mark.parametrize(
    "code,canonical",
    [
        ("en-us", "en"),
        ("eng-latn", "en"),
        ("nb", "nob-latn"),
        ("tl", "fil"),
        ("uk", "ukr-cyrl"),
        ("sr-latn", "srp-latn"),
        ("sr", "srp-cyrl"),
        ("pes-arab", "fas-arab"),
        ("uz-cyrl", "uzn-cyrl"),
    ],
)
def test_iso_aliases_preserve_language_and_script(code: str, canonical: str) -> None:
    assert language_name(code) == LANGUAGES[canonical]


@pytest.mark.parametrize("code", ["cn", "xx", "en-cyrl", "sr-unknown", "zh-hant"])
def test_unknown_codes_do_not_silently_dispatch(code: str) -> None:
    with pytest.raises(ValueError, match="UNSUPPORTED_TARGET_LANGUAGE"):
        language_name(code)


def test_plain_prompt_matches_approved_experiment() -> None:
    assert (
        provider.translation_prompt(" Hello ", language_name("en"), language_name("ru"))
        == "请将以下英语文本翻译为俄语，直接输出翻译结果，不要进行任何解释。\n\nHello"
    )


def test_generation_and_cache_do_not_mix_source_languages(
    monkeypatch: pytest.MonkeyPatch, engine: provider.TranslationEngine
) -> None:
    calls: list[dict[str, object]] = []
    install_native(monkeypatch, [response("first"), response("second")], calls)
    assert engine.translate_text(request(engine))[0] == "first"
    assert engine.translate_text(request(engine))[0] == "first"
    assert engine.translate_text(request(engine, source="fr"))[0] == "second"
    assert len(calls) == 2
    assert calls[0]["temperature"] == 0
    assert calls[0]["cache_prompt"] is False
    assert calls[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert calls[0]["max_tokens"] == 1024


def test_profile_shape_and_language_specific_units(
    monkeypatch: pytest.MonkeyPatch, engine: provider.TranslationEngine
) -> None:
    calls: list[dict[str, object]] = []
    install_native(
        monkeypatch, [response("a"), response("b"), response("c"), response("d")], calls
    )
    value: dict[str, object] = {
        "subject_area": "one",
        "positive_terms": ["two"],
        "excluded_terms": ["three"],
        "excluded_topics": ["four"],
    }
    result = engine.localize(
        ProfileLocalizationRequest(engine.translator_ref, "en", "de", value)
    )
    assert result == {
        "subject_area": "a",
        "positive_terms": ["b"],
        "excluded_terms": ["c"],
        "excluded_topics": ["d"],
    }


def test_full_text_keeps_last_segment_and_does_not_use_excerpt(
    monkeypatch: pytest.MonkeyPatch, engine: provider.TranslationEngine
) -> None:
    calls: list[dict[str, object]] = []
    install_native(monkeypatch, [response("start"), response("end")], calls)
    translated, warnings = engine.translate_text(
        request(engine, "a" * 800 + "\nLAST_SENTENCE")
    )
    assert translated == "start\nend"
    assert "LAST_SENTENCE" in str(calls[1])
    assert warnings == ("MACHINE_TRANSLATION_UNVERIFIED",)


def test_legacy_evidence_only_marks_its_own_excerpt(
    monkeypatch: pytest.MonkeyPatch, engine: provider.TranslationEngine
) -> None:
    calls: list[dict[str, object]] = []
    install_native(monkeypatch, [response("bounded")], calls)
    _, warnings = engine.translate_evidence(request(engine, "a" * 1200))
    assert "REPRESENTATIVE_EXCERPT_TRANSLATED" in warnings
    assert len(str(calls[0])) < 1200


def test_same_language_preserves_complete_text(
    engine: provider.TranslationEngine,
) -> None:
    value = "word " * 400
    assert engine.translate_evidence(request(engine, value, "en", "en")) == (value, ())


def test_length_limited_answer_is_never_returned_as_complete(
    monkeypatch: pytest.MonkeyPatch, engine: provider.TranslationEngine
) -> None:
    calls: list[dict[str, object]] = []
    install_native(
        monkeypatch,
        [response("TRUNCATED", "length"), response("left"), response("right")],
        calls,
    )
    assert engine.translate_text(request(engine, "first second"))[0] == "left\nright"
    assert len(calls) == 3


@pytest.mark.parametrize(
    "value,error",
    [
        ("", "EMPTY_OUTPUT"),
        ("<think>secret</think>answer", "CONTROL_TOKEN_LEAK"),
        ("de> leaked", "CONTROL_TOKEN_LEAK"),
    ],
)
def test_malformed_model_output_is_scoped_to_request(
    monkeypatch: pytest.MonkeyPatch,
    engine: provider.TranslationEngine,
    value: str,
    error: str,
) -> None:
    install_native(monkeypatch, [response(value), response("recovered")], [])
    with pytest.raises(provider.TranslatorRuntimeRequestError, match=error):
        engine.translate_text(request(engine))
    assert engine.runtime_ready
    assert engine.translate_text(request(engine))[0] == "recovered"


def test_http_timeout_kills_native_and_next_request_restarts(
    monkeypatch: pytest.MonkeyPatch, engine: provider.TranslationEngine
) -> None:
    native = engine._process  # pyright: ignore[reportPrivateUsage]
    assert isinstance(native, Mock)

    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("bounded timeout")

    engine._client.close()  # pyright: ignore[reportPrivateUsage]
    engine._client = httpx.Client(  # pyright: ignore[reportPrivateUsage]
        base_url="http://127.0.0.1:8080", transport=httpx.MockTransport(timeout)
    )
    with pytest.raises(TimeoutError, match="DEADLINE"):
        engine.translate_text(request(engine))
    native.kill.assert_called_once()
    assert not engine.runtime_ready
    started: list[float | None] = []

    def start(
        self: provider.TranslationEngine, timeout_seconds: float | None = None
    ) -> None:
        started.append(timeout_seconds)
        self._runtime_loaded = True  # pyright: ignore[reportPrivateUsage]
        self._process = Mock(poll=Mock(return_value=None))  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(provider.TranslationEngine, "_start_runtime", start)
    install_native(monkeypatch, [response("recovered")], [])
    assert engine.translate_text(request(engine))[0] == "recovered"
    assert len(started) == 1 and engine.runtime_ready


def test_native_not_ready_until_confirmed_health(
    monkeypatch: pytest.MonkeyPatch, settings: provider.TranslationSettings
) -> None:
    monkeypatch.setattr(provider, "verify_model_artifacts", noop)

    def version(*args: Any, **kwargs: Any) -> SimpleNamespace:
        del args, kwargs
        return SimpleNamespace(
            stdout="d81235049384534c167caea52b85a694f6103d14", stderr=""
        )

    monkeypatch.setattr(provider.subprocess, "run", version)
    child = Mock(poll=Mock(return_value=None))
    launch = Mock(return_value=child)
    monkeypatch.setattr(provider.subprocess, "Popen", launch)
    attempts = 0

    def health(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        assert req.url.host == "127.0.0.1"
        attempts += 1
        return httpx.Response(503 if attempts == 1 else 200, json={"status": "ok"})

    original = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        return original(**kwargs, transport=httpx.MockTransport(health))

    monkeypatch.setattr(provider.httpx, "Client", client)
    model = provider.TranslationEngine(settings)
    assert attempts == 2 and model.runtime_ready
    arguments = launch.call_args.args[0]
    assert "--log-disable" in arguments and "--no-webui" in arguments
    assert arguments[arguments.index("--host") + 1] == "127.0.0.1"
    model.close()
    child.kill.assert_called_once()


def test_partial_native_revision_does_not_satisfy_full_pin(
    monkeypatch: pytest.MonkeyPatch, settings: provider.TranslationSettings
) -> None:
    monkeypatch.setattr(provider, "verify_model_artifacts", noop)
    monkeypatch.setattr(
        provider.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(stdout="d8123504", stderr="")),
    )
    launch = Mock()
    monkeypatch.setattr(provider.subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="NATIVE_VERSION_MISMATCH"):
        provider.TranslationEngine(settings)
    launch.assert_not_called()


def test_private_boundary_and_version_check(engine: provider.TranslationEngine) -> None:
    with TestClient(provider.create_app(engine)) as connection:
        client = cast(Any, connection)
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/runtimez").json()["translator_ref"] == engine.translator_ref
        assert client.get("/docs").status_code == 404
        payload = {
            "schema_version": "1.0.0",
            "translator_ref": "old-release",
            "source_language": "en",
            "target_language": "de",
            "source_digest": "sha256:" + "a" * 64,
            "text": "source",
        }
        assert client.post("/v1/translate-text", json=payload).status_code == 422


def test_missing_settings_do_not_use_silent_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AELEV_TRANSLATOR_BATCH_SIZE", raising=False)
    monkeypatch.setenv("AELEV_TRANSLATOR_LOCK_PATH", str(ROOT / "translator.lock.json"))
    with pytest.raises(KeyError):
        provider.TranslationSettings.from_environment()
