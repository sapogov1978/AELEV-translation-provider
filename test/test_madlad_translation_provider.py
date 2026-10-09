"""MADLAD provider behavior tests."""

import json
from io import StringIO
from pathlib import Path

import pytest

from translator_service.madlad_translation_provider import (
    MadladTranslationEngine,
    MadladTranslationSettings,
    TranslatorRuntimeRequestError,
    read_madlad_language_tokens,
    read_madlad_translator_lock,
)
from translator_service.protocol import (
    EvidenceTranslationRequest,
    ProfileLocalizationRequest,
)
from translator_service.translator_healthcheck import read_translator_ref


@pytest.fixture(autouse=True)
def _pinned_test_language_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    def tokens(_root: Path) -> frozenset[str]:
        return frozenset(f"<2{code}>" for code in ("en", "ja", "de", "ru", "fil", "no"))

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.read_madlad_language_tokens",
        tokens,
    )


def test_control_tokens_are_read_from_main_unigram_vocabulary(tmp_path: Path) -> None:
    (tmp_path / "tokenizer.json").write_text(
        json.dumps(
            {"model": {"vocab": [["ordinary", -1], ["<2no>", 0], ["<2fil>", 0]]}}
        ),
        encoding="utf-8",
    )
    assert read_madlad_language_tokens(tmp_path) == frozenset({"<2no>", "<2fil>"})


def test_norwegian_alias_and_unknown_language_never_dispatch_an_unknown_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()
    process.stdout = StringIO(
        '{"status":"ready"}\n{"translations":["Pengepolitikk"]}\n'
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )

    def return_process(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        return_process,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=1,
        )
    )
    profile: dict[str, object] = {
        "subject_area": "monetary policy",
        "positive_terms": [],
        "excluded_terms": [],
        "excluded_topics": [],
    }
    with pytest.raises(
        TranslatorRuntimeRequestError, match="UNSUPPORTED_TARGET_LANGUAGE"
    ):
        engine.localize(
            ProfileLocalizationRequest(engine.translator_ref, "en", "cn", profile)
        )
    assert process.stdin.getvalue() == ""
    assert (
        engine.localize(
            ProfileLocalizationRequest(engine.translator_ref, "en", "nb", profile)
        )["subject_area"]
        == "Pengepolitikk"
    )
    assert json.loads(process.stdin.getvalue())["texts"] == ["<2no> monetary policy"]


class _Process:
    def __init__(self) -> None:
        self.returncode: int | None = None
        self.stdin = StringIO()
        self.stdout = StringIO(
            '{"status":"ready"}\n'
            '{"translations":["金融","中央銀行","金利","ポルノ","賭博"]}\n'
        )

    def poll(self) -> int | None:
        return self.returncode


def _skip_verify(settings: MadladTranslationSettings) -> None:
    del settings


def _popen(*args: object, **kwargs: object) -> _Process:
    del args, kwargs
    return _Process()


def test_model_health_is_not_ready_before_runtime_handshake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()

    def return_process(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    def read_ready(
        engine: MadladTranslationEngine, child: _Process, timeout: float
    ) -> str:
        del timeout
        assert engine.runtime_ready is False
        return child.stdout.readline()

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        return_process,
    )
    monkeypatch.setattr(MadladTranslationEngine, "_read_line", read_ready)
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=1,
        )
    )
    assert engine.runtime_ready is True
    process.returncode = 0
    engine.close()
    assert engine.runtime_ready is False


def test_madlad_engine_uses_target_token_and_preserves_profile_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _popen()

    def return_process(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        return_process,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )

    localized = engine.localize(
        ProfileLocalizationRequest(
            translator_ref=engine.translator_ref,
            source_language="en",
            target_language="ja",
            profile={
                "subject_area": "finance",
                "positive_terms": ["central bank", "interest rates"],
                "excluded_terms": ["porn"],
                "excluded_topics": ["gambling"],
            },
        )
    )

    assert localized == {
        "subject_area": "金融",
        "positive_terms": ["中央銀行", "金利"],
        "excluded_terms": ["ポルノ"],
        "excluded_topics": ["賭博"],
    }
    assert engine.runtime_ready is True
    process.returncode = 137
    assert engine.runtime_ready is False
    request = json.loads(process.stdin.getvalue())
    assert request["texts"] == [
        "<2ja> finance",
        "<2ja> central bank",
        "<2ja> interest rates",
        "<2ja> porn",
        "<2ja> gambling",
    ]


def test_madlad_engine_maps_tagalog_to_supported_filipino_control_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()
    process.stdout = StringIO(
        '{"status":"ready"}\n'
        '{"translations":["Pananalapi","sentral na bangko",'
        '"pornograpiya","pagtaya sa palakasan"]}\n'
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )

    def return_process(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        return_process,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )

    localized = engine.localize(
        ProfileLocalizationRequest(
            translator_ref=engine.translator_ref,
            source_language="en",
            target_language="tl",
            profile={
                "subject_area": "finance",
                "positive_terms": ["central bank"],
                "excluded_terms": ["pornography"],
                "excluded_topics": ["sports betting"],
            },
        )
    )

    assert localized["positive_terms"] == ["sentral na bangko"]
    request = json.loads(process.stdin.getvalue())
    assert request["texts"] == [
        "<2fil> finance",
        "<2fil> central bank",
        "<2fil> pornography",
        "<2fil> sports betting",
    ]


def test_madlad_engine_rejects_leaked_control_token_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()
    process.stdout = StringIO(
        '{"status":"ready"}\n'
        '{"translations":["> Pananalapi","sentral na bangko",'
        '"pornograpiya","pagtaya sa palakasan"]}\n'
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )

    def return_process(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        return_process,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )

    with pytest.raises(
        TranslatorRuntimeRequestError,
        match="TRANSLATOR_CONTROL_TOKEN_LEAK",
    ):
        engine.localize(
            ProfileLocalizationRequest(
                translator_ref=engine.translator_ref,
                source_language="en",
                target_language="tl",
                profile={
                    "subject_area": "finance",
                    "positive_terms": ["central bank"],
                    "excluded_terms": ["pornography"],
                    "excluded_topics": ["sports betting"],
                },
            )
        )


def test_madlad_engine_translates_bounded_operator_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()
    process.stdout = StringIO(
        '{"status":"ready"}\n'
        '{"translations":["Банк Финляндии отвечает за денежно-кредитную политику."]}\n'
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )

    def evidence_popen(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        evidence_popen,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )

    translated, warnings = engine.translate_evidence(
        EvidenceTranslationRequest(
            translator_ref=engine.translator_ref,
            source_language="fi",
            target_language="ru",
            source_digest="sha256:" + "b" * 64,
            text="Suomen Pankki vastaa rahapolitiikasta.",
        )
    )

    assert translated.startswith("Банк Финляндии")
    assert warnings == ("MACHINE_TRANSLATION_UNVERIFIED",)
    assert json.loads(process.stdin.getvalue())["texts"] == [
        "<2ru> Suomen Pankki vastaa rahapolitiikasta."
    ]


def test_generic_translation_uses_the_complete_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        _popen,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )
    captured: list[str] = []

    def translate(
        values: list[str], *, target: str, max_output_tokens: int | None = None
    ) -> list[str]:
        assert target == "ru"
        assert max_output_tokens is None
        captured.extend(values)
        return ["перевод " + value for value in values]

    monkeypatch.setattr(engine, "_translate", translate)
    source = ("complete source sentence " * 80).strip()
    translated, warnings = engine.translate_text(
        EvidenceTranslationRequest(
            translator_ref=engine.translator_ref,
            source_language="en",
            target_language="ru",
            source_digest="sha256:" + "b" * 64,
            text=source,
        )
    )
    assert sum(len(value) for value in captured) > 768
    assert "REPRESENTATIVE_EXCERPT_TRANSLATED" not in warnings
    assert translated.count("перевод ") == len(captured)


def test_madlad_engine_restarts_stopped_runtime_before_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stopped = _Process()
    replacement = _Process()
    replacement.stdout = StringIO(
        '{"status":"ready"}\n{"translations":["Банк Финляндии"]}\n'
    )
    processes = iter((stopped, replacement))
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )

    def next_process(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return next(processes)

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        next_process,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )
    stopped.returncode = 137

    translated, _warnings = engine.translate_evidence(
        EvidenceTranslationRequest(
            translator_ref=engine.translator_ref,
            source_language="fi",
            target_language="ru",
            source_digest="sha256:" + "b" * 64,
            text="Suomen Pankki",
        )
    )

    assert translated == "Банк Финляндии"
    assert engine.runtime_ready is True
    assert json.loads(replacement.stdin.getvalue())["texts"] == ["<2ru> Suomen Pankki"]


def test_madlad_engine_keeps_runtime_error_scoped_to_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()
    process.stdout = StringIO(
        '{"status":"ready"}\n{"error":"TRANSLATOR_EMPTY_OUTPUT"}\n'
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )

    def return_runtime(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        return_runtime,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )

    with pytest.raises(TranslatorRuntimeRequestError, match="EMPTY_OUTPUT"):
        engine.translate_evidence(
            EvidenceTranslationRequest(
                translator_ref=engine.translator_ref,
                source_language="fi",
                target_language="ru",
                source_digest="sha256:" + "b" * 64,
                text="Suomen Pankki",
            )
        )

    assert engine.runtime_ready is True


def test_madlad_engine_translates_representative_operator_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _Process()
    process.stdout = StringIO(
        '{"status":"ready"}\n{"translations":["репрезентативный перевод"]}\n'
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        _skip_verify,
    )

    def return_runtime(*args: object, **kwargs: object) -> _Process:
        del args, kwargs
        return process

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        return_runtime,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            model_root=Path("/model"),
            lock_path=Path("/lock"),
            socket_path=Path("/run/translator.sock"),
            translator_ref="google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            artifacts={},
            batch_size=8,
        )
    )

    translated, warnings = engine.translate_evidence(
        EvidenceTranslationRequest(
            translator_ref=engine.translator_ref,
            source_language="en",
            target_language="ru",
            source_digest="sha256:" + "b" * 64,
            text="a" * 1_200 + "b" * 1_200 + "c" * 1_200,
        )
    )

    request = json.loads(process.stdin.getvalue())
    assert translated == "репрезентативный перевод"
    assert "REPRESENTATIVE_EXCERPT_TRANSLATED" in warnings
    assert request["max_output_tokens"] == 96
    assert sum(len(value.removeprefix("<2ru> ")) for value in request["texts"]) < 800
    assert request["texts"][0].startswith("<2ru> " + "a" * 20)
    assert request["texts"][-1].endswith("c" * 20)


def test_madlad_translator_lock_pins_selected_offline_release() -> None:
    path = Path("/opt/aelev/translator.lock.json")
    if not path.is_file():
        pytest.skip("translator lock is not mounted")

    translator_ref, artifacts = read_madlad_translator_lock(path)
    lock = json.loads(path.read_text(encoding="utf-8"))

    assert translator_ref.startswith("google/madlad400-3b-mt-q4k@sha256:")
    assert lock["status"] == "SELECTED_PRODUCTION"
    assert lock["license"] == "Apache-2.0"
    assert lock["selection_policy"] == "QUALITY_FIRST_BEST_MEASURED_WITH_RECHECK"
    assert lock["selection_evidence"]["known_semantic_failures"] == 0
    assert set(artifacts) == {
        "added_tokens.json",
        "config.json",
        "generation_config.json",
        "model-q4k.gguf",
        "special_tokens_map.json",
        "spiece.model",
        "tokenizer.json",
        "tokenizer_config.json",
    }


def test_madlad_translator_rejects_unselected_lock(tmp_path: Path) -> None:
    source = Path("/opt/aelev/translator.lock.json")
    if not source.is_file():
        pytest.skip("translator lock is not mounted")
    lock = json.loads(source.read_text(encoding="utf-8"))
    lock["status"] = "REJECTED"
    path = tmp_path / "translator.lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")

    with pytest.raises(RuntimeError, match="metadata"):
        read_madlad_translator_lock(path)


def test_translator_healthcheck_reads_selected_madlad_ref(tmp_path: Path) -> None:
    path = tmp_path / "translator.lock.json"
    path.write_text(
        json.dumps(
            {
                "status": "SELECTED_PRODUCTION",
                "architecture": "T5ForConditionalGeneration",
                "translator_ref": "google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
            }
        ),
        encoding="utf-8",
    )

    assert read_translator_ref(path).startswith("google/madlad400-3b-mt-q4k@")
