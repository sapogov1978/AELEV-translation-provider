from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ghcr.io/example/provider@sha256:" + "a" * 64


def load_smoke() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "quality_smoke", ROOT / "tools/release_quality_smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, image: str = IMAGE
) -> tuple[ModuleType, Path]:
    module = load_smoke()
    output = tmp_path / "evidence.json"
    corpus = tmp_path / "cases.json"
    corpus.write_text(
        json.dumps(
            [
                {
                    "id": str(index),
                    "source": "en",
                    "target": "ru",
                    "text": "Keep request_id unchanged.",
                    "checks": {"required": ["request_id"]},
                }
                for index in range(20)
            ]
        )
    )
    monkeypatch.setattr(module, "CORPUS", corpus)
    monkeypatch.setattr(
        sys,
        "argv",
        ["smoke", "--socket", "/unused", "--image", image, "--output", str(output)],
    )
    return module, output


def test_mutable_image_is_rejected_before_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, output = configure(monkeypatch, tmp_path, "ghcr.io/example/provider:latest")
    with pytest.raises(RuntimeError, match="QUALITY_IMAGE_DIGEST_REQUIRED"):
        module.main()
    assert not output.exists()


def test_literal_failure_is_saved_before_the_gate_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, output = configure(monkeypatch, tmp_path)

    def translate(*_: object) -> tuple[str, tuple[str, ...]]:
        return "identifier lost", ()

    monkeypatch.setattr(module, "translate", translate)
    with pytest.raises(RuntimeError, match="QUALITY_LITERAL_FAILURE:0"):
        module.main()
    evidence = json.loads(output.read_text())
    assert evidence["status"] == "FAIL"
    assert evidence["case_count"] == 1
    assert evidence["results"][0]["failures"] == ["missing:request_id"]
    assert "identifier lost" not in output.read_text()


def test_transport_failure_retains_completed_case_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, output = configure(monkeypatch, tmp_path)
    attempts = 0

    def translate(*_: object) -> tuple[str, tuple[str, ...]]:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("QUALITY_PROVIDER_HTTP_503")
        return "request_id", ("MACHINE_TRANSLATION_UNVERIFIED",)

    monkeypatch.setattr(module, "translate", translate)
    with pytest.raises(RuntimeError, match="QUALITY_PROVIDER_HTTP_503"):
        module.main()
    evidence = json.loads(output.read_text())
    assert attempts == 2
    assert evidence["status"] == "FAIL"
    assert evidence["results"][0]["status"] == "PASS"
    assert evidence["results"][1]["status"] == "FAILED"


def test_raw_evidence_is_opt_in_and_semantic_review_is_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, output = configure(monkeypatch, tmp_path)
    raw = tmp_path / "raw.json"
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--raw-output", str(raw)])

    def translate(*_: object) -> tuple[str, tuple[str, ...]]:
        return "request_id", ("MACHINE_TRANSLATION_UNVERIFIED",)

    monkeypatch.setattr(module, "translate", translate)
    module.main()
    evidence = json.loads(output.read_text())
    exchanges = json.loads(raw.read_text())
    assert evidence["status"] == "PASS" and evidence["case_count"] == 20
    assert evidence["semantic_review"] == "REQUIRED_SEPARATELY"
    assert len(exchanges) == 20
    assert exchanges[0]["request"]["text"] == "Keep request_id unchanged."
    assert exchanges[0]["response"]["translated_text"] == "request_id"
