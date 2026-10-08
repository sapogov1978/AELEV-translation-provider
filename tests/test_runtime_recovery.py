import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from translator_service.madlad_translation_provider import (
    MadladTranslationEngine,
    MadladTranslationSettings,
)


@pytest.fixture(autouse=True)
def language_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    def tokens(_root: Path) -> frozenset[str]:
        return frozenset({"<2ja>", "<2ru>", "<2en>"})

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.read_madlad_language_tokens",
        tokens,
    )


def test_translator_deadline_kills_inference_and_next_request_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[str]] = []

    def start(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        del args, kwargs
        delay = "import time; time.sleep(30)" if not children else ""
        script = (
            'import sys, json\nprint(\'{"status":"ready"}\', flush=True)\n'
            "for line in sys.stdin:\n"
            f" {delay or 'pass'}\n"
            " print(json.dumps({'translations': ['translated']}), flush=True)\n"
        )
        process = real_popen(
            [sys.executable, "-u", "-c", script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        children.append(process)
        return process

    def skip_verify(settings: MadladTranslationSettings) -> None:
        del settings

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        skip_verify,
    )
    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.subprocess.Popen",
        start,
    )
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            Path("/unused"),
            Path("/unused"),
            Path("/unused"),
            "test",
            {},
            1,
            request_timeout_seconds=20,
            segment_timeout_seconds=5,
        )
    )
    try:
        with pytest.raises(TimeoutError, match="DEADLINE"):
            engine._translate(["finance"], target="ja")  # pyright: ignore[reportPrivateUsage]
        assert children[0].poll() is not None
        assert not engine.runtime_ready
        assert engine._translate(["finance"], target="ja") == ["translated"]  # pyright: ignore[reportPrivateUsage]
        assert len(children) == 2
        # Successful units survive a retry without more inference.
        assert engine._translate(["finance"], target="ja") == ["translated"]  # pyright: ignore[reportPrivateUsage]
    finally:
        engine._stop_runtime()  # pyright: ignore[reportPrivateUsage]


def test_operator_translation_interleaves_between_profile_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def skip_verify(settings: MadladTranslationSettings) -> None:
        del settings

    def skip_start(
        self: MadladTranslationEngine,
        timeout_seconds: float | None = None,
    ) -> None:
        del self, timeout_seconds

    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def translate(
        self: MadladTranslationEngine,
        request: str,
        *,
        deadline: float,
    ) -> object:
        del self, deadline
        value = str(json.loads(request)["texts"][0])
        calls.append(value)
        if value == "<2ja> profile-one":
            started.set()
            assert release.wait(3)
        return {"translations": [value.replace("<2ja> ", "translated-")]}

    monkeypatch.setattr(
        "translator_service.madlad_translation_provider.verify_model_artifacts",
        skip_verify,
    )
    monkeypatch.setattr(MadladTranslationEngine, "_start_runtime", skip_start)
    monkeypatch.setattr(MadladTranslationEngine, "_request_batch", translate)
    engine = MadladTranslationEngine(
        MadladTranslationSettings(
            Path("/unused"),
            Path("/unused"),
            Path("/unused"),
            "test",
            {},
            1,
        )
    )
    failures: list[Exception] = []

    def run(values: list[str]) -> None:
        try:
            engine._translate(values, target="ja")  # pyright: ignore[reportPrivateUsage]
        except Exception as error:
            failures.append(error)

    profile = threading.Thread(target=run, args=(["profile-one", "profile-two"],))
    review = threading.Thread(target=run, args=(["operator"],))
    profile.start()
    try:
        assert started.wait(3)
        review.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            with engine._condition:  # pyright: ignore[reportPrivateUsage]
                if len(engine._tickets) == 2:  # pyright: ignore[reportPrivateUsage]
                    break
            time.sleep(0.001)
        else:
            pytest.fail("operator request did not queue")
    finally:
        release.set()
        profile.join(timeout=3)
        if review.ident is not None:
            review.join(timeout=3)
    assert not failures
    assert calls == ["<2ja> profile-one", "<2ja> operator", "<2ja> profile-two"]
