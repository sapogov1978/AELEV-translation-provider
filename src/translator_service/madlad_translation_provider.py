"""Pinned offline MADLAD-400 provider for subject-profile localization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import threading
import time
from collections import OrderedDict, deque
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Annotated, cast

import uvicorn
from fastapi import Body, FastAPI, HTTPException

from translator_service.environment import getenv
from translator_service.protocol import (
    EvidenceTranslationRequest,
    ProfileLocalizationRequest,
    TranslatorConfigurationError,
    parse_evidence_translation_request,
    parse_profile_localization_request,
)

_FIELDS = ("subject_area", "positive_terms", "excluded_terms", "excluded_topics")
_EVIDENCE_SEGMENT_CHARACTERS = 800
_OPERATOR_TRANSLATION_CHARACTERS = 768
_OPERATOR_TRANSLATION_OUTPUT_TOKENS = 96
_MADLAD_LANGUAGE_ALIASES = {
    # The application keeps the ISO 639-1 code for Tagalog, while MADLAD's
    # tokenizer exposes the translation control token under Filipino.
    "tl": "fil",
    # The pinned tokenizer names Norwegian Bokmal under generic Norwegian.
    "nb": "no",
}
_RUNTIME_REQUEST_ERRORS = {
    "TRANSLATOR_UNSUPPORTED_TARGET_LANGUAGE",
    "TRANSLATOR_CONTROL_TOKEN_LEAK",
    "TRANSLATOR_EMPTY_OUTPUT",
    "TRANSLATOR_RUNTIME_REQUEST_FAILED",
    "TRANSLATOR_RUNTIME_REQUEST_INVALID",
}


class TranslatorRuntimeRequestError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MadladTranslationSettings:
    model_root: Path
    lock_path: Path
    socket_path: Path
    translator_ref: str
    artifacts: dict[str, tuple[str, int]]
    batch_size: int
    request_timeout_seconds: float = 240
    segment_timeout_seconds: float = 180

    @classmethod
    def from_environment(cls) -> MadladTranslationSettings:
        lock_path = Path(
            os.environ.get(
                "AELEV_TRANSLATOR_LOCK_PATH", "/opt/aelev/translator.lock.json"
            )
        )
        translator_ref, artifacts = read_madlad_translator_lock(lock_path)
        batch_size = int(os.environ.get("AELEV_TRANSLATOR_BATCH_SIZE", "1"))
        if not 1 <= batch_size <= 32:
            raise RuntimeError("translator batch size must be between 1 and 32")
        request_timeout = float(
            getenv("AELEV_TRANSLATOR_REQUEST_TIMEOUT_SECONDS", "240")
        )
        segment_timeout = float(
            getenv("AELEV_TRANSLATOR_SEGMENT_TIMEOUT_SECONDS", "180")
        )
        if not 0 < segment_timeout <= request_timeout <= 240:
            raise RuntimeError(
                "translator deadlines must satisfy 0 < segment <= request <= 240"
            )
        return cls(
            model_root=Path(_required("AELEV_TRANSLATOR_MODEL_ROOT")),
            lock_path=lock_path,
            socket_path=Path(_required("AELEV_TRANSLATOR_SOCKET_PATH")),
            translator_ref=translator_ref,
            artifacts=artifacts,
            batch_size=batch_size,
            request_timeout_seconds=request_timeout,
            segment_timeout_seconds=segment_timeout,
        )


class MadladTranslationEngine:
    def __init__(self, settings: MadladTranslationSettings) -> None:
        verify_model_artifacts(settings)
        self._binary = os.environ.get(
            "AELEV_TRANSLATOR_RUNTIME_PATH", "/usr/local/bin/aelev-madlad-runtime"
        )
        self._model_root = settings.model_root
        self._process: subprocess.Popen[str] | None = None
        self._runtime_loaded = False
        self._translator_ref = settings.translator_ref
        self._language_tokens = read_madlad_language_tokens(settings.model_root)
        self._batch_size = settings.batch_size
        self._request_timeout = settings.request_timeout_seconds
        self._segment_timeout = settings.segment_timeout_seconds
        self._condition = threading.Condition()
        self._tickets: deque[object] = deque()
        self._cache: OrderedDict[str, list[str]] = OrderedDict()
        self._start_runtime()

    def _start_runtime(self, timeout_seconds: float | None = None) -> None:
        try:
            self._launch_runtime(timeout_seconds)
        except Exception:
            self._stop_runtime()
            raise

    def _launch_runtime(self, timeout_seconds: float | None) -> None:
        self._runtime_loaded = False
        process = subprocess.Popen(
            [self._binary, str(self._model_root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._process = process
        if process.stdout is None or process.stdin is None:
            raise RuntimeError("translator runtime pipes are unavailable")
        ready_line = self._read_line(
            process,
            self._segment_timeout if timeout_seconds is None else timeout_seconds,
        )
        try:
            ready = cast(object, json.loads(ready_line))
        except json.JSONDecodeError as error:
            self._stop_runtime()
            raise RuntimeError("translator runtime did not become ready") from error
        if ready != {"status": "ready"}:
            self._stop_runtime()
            raise RuntimeError("translator runtime did not become ready")
        self._process = process
        self._runtime_loaded = True

    def _read_line(self, process: subprocess.Popen[str], timeout: float) -> str:
        responses: Queue[str | Exception] = Queue(maxsize=1)

        def read() -> None:
            try:
                assert process.stdout is not None
                responses.put(process.stdout.readline())
            except (OSError, ValueError) as error:
                responses.put(error)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        try:
            result = responses.get(timeout=max(0, timeout))
        except Empty as error:
            self._stop_runtime()
            reader.join(timeout=1)
            raise TimeoutError("TRANSLATOR_DEADLINE_EXCEEDED") from error
        if isinstance(result, Exception):
            raise RuntimeError("translator runtime read failed") from result
        return result

    @contextmanager
    def _runtime_slot(self, deadline: float) -> Generator[None]:
        # FIFO at translation-unit granularity lets short operator requests
        # interleave with a long profile without loading another copy of weights.
        ticket = object()
        with self._condition:
            self._tickets.append(ticket)
            while self._tickets[0] is not ticket:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._tickets.remove(ticket)
                    raise TimeoutError("TRANSLATOR_DEADLINE_EXCEEDED")
                self._condition.wait(remaining)
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError("TRANSLATOR_DEADLINE_EXCEEDED")
            yield
        finally:
            with self._condition:
                self._tickets.popleft()
                self._condition.notify_all()

    @property
    def translator_ref(self) -> str:
        return self._translator_ref

    @property
    def runtime_ready(self) -> bool:
        process = self._process
        return self._runtime_loaded and process is not None and process.poll() is None

    def localize(self, request: ProfileLocalizationRequest) -> dict[str, object]:
        if request.source_language == request.target_language:
            return request.profile
        values: list[str] = [cast(str, request.profile["subject_area"])]
        lengths: dict[str, int] = {}
        for field in _FIELDS[1:]:
            items = cast(list[str], request.profile[field])
            lengths[field] = len(items)
            values.extend(items)
        translated = self._translate(values, target=request.target_language)
        offset = 1
        result: dict[str, object] = {"subject_area": translated[0]}
        for field in _FIELDS[1:]:
            end = offset + lengths[field]
            result[field] = translated[offset:end]
            offset = end
        return result

    def translate_evidence(
        self, request: EvidenceTranslationRequest
    ) -> tuple[str, tuple[str, ...]]:
        if request.source_language == request.target_language:
            return request.text, ()
        evidence, excerpted = _operator_translation_evidence(request.text)
        segments = _evidence_segments(evidence)
        translated = "\n".join(
            self._translate(
                list(segments),
                target=request.target_language,
                max_output_tokens=_OPERATOR_TRANSLATION_OUTPUT_TOKENS,
            )
        ).strip()
        warnings = ["MACHINE_TRANSLATION_UNVERIFIED"]
        if excerpted:
            warnings.append("REPRESENTATIVE_EXCERPT_TRANSLATED")
        if translated.casefold() == evidence.casefold():
            warnings.append("UNCHANGED_OUTPUT")
        return translated, tuple(warnings)

    def translate_text(
        self, request: EvidenceTranslationRequest
    ) -> tuple[str, tuple[str, ...]]:
        """Translate the complete bounded text without client-specific summarizing."""
        if request.source_language == request.target_language:
            return request.text, ()
        segments = _evidence_segments(request.text)
        translated = "\n".join(
            self._translate(list(segments), target=request.target_language)
        ).strip()
        warnings = ["MACHINE_TRANSLATION_UNVERIFIED"]
        if translated.casefold() == request.text.strip().casefold():
            warnings.append("UNCHANGED_OUTPUT")
        return translated, tuple(warnings)

    def _translate(
        self,
        values: list[str],
        *,
        target: str,
        max_output_tokens: int | None = None,
    ) -> list[str]:
        translated: list[str] = []
        target_code = _madlad_language_code(target)
        if f"<2{target_code}>" not in self._language_tokens:
            raise TranslatorRuntimeRequestError(
                "TRANSLATOR_UNSUPPORTED_TARGET_LANGUAGE"
            )
        deadline = time.monotonic() + self._request_timeout
        for offset in range(0, len(values), self._batch_size):
            with self._runtime_slot(deadline):
                batch = values[offset : offset + self._batch_size]
                payload: dict[str, object] = {
                    "texts": [f"<2{target_code}> {value}" for value in batch]
                }
                if max_output_tokens is not None:
                    payload["max_output_tokens"] = max_output_tokens
                request = json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                cached = self._cache.get(request)
                if cached is not None:
                    self._cache.move_to_end(request)
                    translated.extend(cached)
                    continue
                response = self._request_batch(request, deadline=deadline)
                if not isinstance(response, dict):
                    raise RuntimeError("translator runtime response is invalid")
                document = cast(dict[str, object], response)
                if set(document) == {"error"}:
                    error_code = document.get("error")
                    if (
                        not isinstance(error_code, str)
                        or error_code not in _RUNTIME_REQUEST_ERRORS
                    ):
                        raise RuntimeError("translator runtime response is invalid")
                    raise TranslatorRuntimeRequestError(error_code)
                if set(document) != {"translations"}:
                    raise RuntimeError("translator runtime response is invalid")
                raw_translations = document.get("translations")
                if not isinstance(raw_translations, list):
                    raise RuntimeError("translator runtime response is invalid")
                items = cast(list[object], raw_translations)
                if any(not isinstance(item, str) for item in items):
                    raise RuntimeError("translator runtime response is invalid")
                translated_batch = cast(list[str], items)
                if any(_has_control_token_leak(item) for item in translated_batch):
                    raise TranslatorRuntimeRequestError("TRANSLATOR_CONTROL_TOKEN_LEAK")
                if len(translated_batch) != len(batch) or any(
                    not item for item in translated_batch
                ):
                    raise RuntimeError("translator produced an incomplete translation")
                self._cache[request] = translated_batch
                if len(self._cache) > 2048:
                    self._cache.popitem(last=False)
                translated.extend(translated_batch)
        if len(translated) != len(values) or any(not item for item in translated):
            raise RuntimeError("translator produced an incomplete translation")
        return translated

    def _request_batch(self, request: str, *, deadline: float) -> object:
        last_error: Exception | None = None
        for attempt in range(2):
            if time.monotonic() >= deadline:
                raise TimeoutError("TRANSLATOR_DEADLINE_EXCEEDED")
            process = self._process
            if process is None or process.poll() is not None:
                try:
                    self._restart_runtime(deadline)
                except RuntimeError as error:
                    last_error = error
                    continue
                process = self._process
            if process is None or process.stdin is None or process.stdout is None:
                last_error = RuntimeError("translator runtime pipes are unavailable")
                continue
            try:
                process.stdin.write(request + "\n")
                process.stdin.flush()
                line = self._read_line(
                    process, min(self._segment_timeout, deadline - time.monotonic())
                )
                if not line:
                    raise BrokenPipeError("translator runtime closed stdout")
                return cast(object, json.loads(line))
            except (BrokenPipeError, json.JSONDecodeError) as error:
                last_error = error
                if attempt == 0:
                    self._restart_runtime(deadline)
        raise RuntimeError("translator runtime failed after restart") from last_error

    def _restart_runtime(self, deadline: float) -> None:
        self._stop_runtime()
        self._start_runtime(
            min(self._segment_timeout, max(0, deadline - time.monotonic()))
        )

    def _stop_runtime(self) -> None:
        self._runtime_loaded = False
        process = self._process
        self._process = None
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()

    def close(self) -> None:
        self._stop_runtime()


def create_app(engine: MadladTranslationEngine) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            engine.close()

    app = FastAPI(
        title="AELEV translator private model",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        if not engine.runtime_ready:
            raise HTTPException(status_code=503, detail="translator runtime stopped")
        return {"status": "ok", "translator_ref": engine.translator_ref}

    @app.post("/v1/localize-profile")
    def localize(payload: Annotated[object, Body()]) -> dict[str, object]:
        try:
            request = parse_profile_localization_request(
                payload, expected_translator_ref=engine.translator_ref
            )
            localized = engine.localize(request)
        except TranslatorConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except TranslatorRuntimeRequestError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except TimeoutError as error:
            raise HTTPException(
                status_code=503, detail="TRANSLATOR_UNAVAILABLE"
            ) from error
        return {
            "schema_version": "1.0.0",
            "translator_ref": engine.translator_ref,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "target_control_token": "<2"
            + _madlad_language_code(request.target_language)
            + ">",
            "profile": localized,
        }

    @app.post("/v1/translate-evidence")
    def translate_evidence(payload: Annotated[object, Body()]) -> dict[str, object]:
        try:
            request = parse_evidence_translation_request(
                payload, expected_translator_ref=engine.translator_ref
            )
            translated_text, warnings = engine.translate_evidence(request)
        except TranslatorConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except TranslatorRuntimeRequestError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except TimeoutError as error:
            raise HTTPException(
                status_code=503, detail="TRANSLATOR_UNAVAILABLE"
            ) from error
        return {
            "schema_version": "1.0.0",
            "translator_ref": engine.translator_ref,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "source_digest": request.source_digest,
            "translated_text": translated_text,
            "warnings": list(warnings),
        }

    @app.post("/v1/translate-text")
    def translate_text(payload: Annotated[object, Body()]) -> dict[str, object]:
        try:
            request = parse_evidence_translation_request(
                payload, expected_translator_ref=engine.translator_ref
            )
            translated_text, warnings = engine.translate_text(request)
        except TranslatorConfigurationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except TranslatorRuntimeRequestError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except TimeoutError as error:
            raise HTTPException(
                status_code=503, detail="TRANSLATOR_UNAVAILABLE"
            ) from error
        return {
            "schema_version": "1.0.0",
            "translator_ref": engine.translator_ref,
            "source_language": request.source_language,
            "target_language": request.target_language,
            "source_digest": request.source_digest,
            "translated_text": translated_text,
            "warnings": list(warnings),
        }

    return app


def _evidence_segments(text: str) -> tuple[str, ...]:
    """Split preserved evidence into bounded deterministic translation units."""
    segments: list[str] = []
    for paragraph in re.split(r"\n+", text):
        remaining = paragraph.strip()
        while remaining:
            if len(remaining) <= _EVIDENCE_SEGMENT_CHARACTERS:
                segments.append(remaining)
                break
            boundary = remaining.rfind(" ", 0, _EVIDENCE_SEGMENT_CHARACTERS + 1)
            if boundary < _EVIDENCE_SEGMENT_CHARACTERS // 2:
                boundary = _EVIDENCE_SEGMENT_CHARACTERS
            segments.append(remaining[:boundary].strip())
            remaining = remaining[boundary:].strip()
    if not segments:
        raise RuntimeError("translator evidence text is empty")
    return tuple(segments)


def _operator_translation_evidence(text: str) -> tuple[str, bool]:
    normalized = text.strip()
    if len(normalized) <= _OPERATOR_TRANSLATION_CHARACTERS:
        return normalized, False
    part_size = _OPERATOR_TRANSLATION_CHARACTERS // 3
    middle_start = max(0, len(normalized) // 2 - part_size // 2)
    parts = (
        normalized[:part_size].strip(),
        normalized[middle_start : middle_start + part_size].strip(),
        normalized[-part_size:].strip(),
    )
    return " … ".join(parts), True


def _madlad_language_code(language: str) -> str:
    canonical = language.split("-", maxsplit=1)[0]
    return _MADLAD_LANGUAGE_ALIASES.get(canonical, canonical)


def read_madlad_language_tokens(model_root: Path) -> frozenset[str]:
    """Read control tokens only from the hash-verified pinned tokenizer."""
    document = json.loads((model_root / "tokenizer.json").read_text(encoding="utf-8"))
    vocabulary = document["model"]["vocab"]
    if not isinstance(vocabulary, list):
        raise RuntimeError("translator tokenizer vocabulary is invalid")
    tokens: set[str] = set()
    for raw_item in cast(list[object], vocabulary):
        if not isinstance(raw_item, list):
            continue
        item = cast(list[object], raw_item)
        if (
            len(item) == 2
            and isinstance(item[0], str)
            and re.fullmatch(r"<2[a-zA-Z0-9_]+>", item[0])
        ):
            tokens.add(item[0])
    if not tokens:
        raise RuntimeError("translator tokenizer language tokens are unavailable")
    return frozenset(tokens)


def _has_control_token_leak(value: str) -> bool:
    normalized = value.lstrip()
    return bool(re.match(r"^(?:[a-z]{2,3})?>\s", normalized, re.IGNORECASE))


def read_madlad_translator_lock(
    path: Path,
) -> tuple[str, dict[str, tuple[str, int]]]:
    value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    if not isinstance(value, dict):
        raise RuntimeError("translator lock is invalid")
    lock = cast(dict[str, object], value)
    if (
        lock.get("schema_version") != "1.0.0"
        or lock.get("status") != "SELECTED_PRODUCTION"
        or lock.get("model") != "google/madlad400-3b-mt"
        or lock.get("license") != "Apache-2.0"
        or lock.get("architecture") != "T5ForConditionalGeneration"
    ):
        raise RuntimeError("translator lock metadata is invalid")
    translator_ref = lock.get("translator_ref")
    raw_files = lock.get("files")
    if not isinstance(translator_ref, str) or not isinstance(raw_files, list):
        raise RuntimeError("translator lock fields are invalid")
    artifacts: dict[str, tuple[str, int]] = {}
    for raw in cast(list[object], raw_files):
        if not isinstance(raw, dict):
            raise RuntimeError("translator artifact is invalid")
        item = cast(dict[str, object], raw)
        name, digest, size = item.get("path"), item.get("sha256"), item.get("size")
        if (
            not isinstance(name, str)
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size, int)
            or size < 1
        ):
            raise RuntimeError("translator artifact is invalid")
        artifacts[name] = (digest, size)
    expected = {
        "added_tokens.json",
        "config.json",
        "generation_config.json",
        "model-q4k.gguf",
        "special_tokens_map.json",
        "spiece.model",
        "tokenizer.json",
        "tokenizer_config.json",
    }
    if set(artifacts) != expected:
        raise RuntimeError("translator artifact set is invalid")
    return translator_ref, artifacts


def verify_model_artifacts(settings: MadladTranslationSettings) -> None:
    translator_ref, artifacts = read_madlad_translator_lock(settings.lock_path)
    if (translator_ref, artifacts) != (settings.translator_ref, settings.artifacts):
        raise RuntimeError("translator lock changed after startup")
    for name, (digest, size) in artifacts.items():
        path = settings.model_root / name
        if path.stat().st_size != size:
            raise RuntimeError(f"translator artifact {name} has an invalid size")
        checksum = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
        if checksum.hexdigest() != digest:
            raise RuntimeError(f"translator artifact {name} failed verification")


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable {name} is missing")
    return value


def _serve(settings: MadladTranslationSettings) -> None:
    settings.socket_path.parent.mkdir(parents=True, exist_ok=True)
    if settings.socket_path.exists():
        if not stat.S_ISSOCK(settings.socket_path.stat().st_mode):
            raise RuntimeError("translator socket path exists and is not a socket")
        settings.socket_path.unlink()
    uvicorn.run(
        create_app(MadladTranslationEngine(settings)),
        uds=str(settings.socket_path),
        access_log=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("serve", "verify-model"))
    settings = MadladTranslationSettings.from_environment()
    if parser.parse_args().command == "serve":
        _serve(settings)
    else:
        verify_model_artifacts(settings)


if __name__ == "__main__":
    main()
