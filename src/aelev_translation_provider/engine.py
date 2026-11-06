"""Pinned offline translation implementation owned by this provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from aelev_translation_provider.contract import ProviderRequestError
from aelev_translation_provider.languages import language_name

MODEL_FILE = "Index-Translate-9B.Q4_K_M.gguf"
NATIVE_ORIGIN = "http://127.0.0.1:8080"


class ProviderUnavailable(RuntimeError):
    """A bounded technical failure that must remain retryable to the caller."""


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("PROVIDER_LOCK_INVALID")
    return cast(dict[str, Any], value)


def execution_reference(model_digest: str, runtime: dict[str, Any]) -> str:
    """Pin weights and the complete immutable inference profile together."""
    profile = json.dumps(
        {"model_sha256": model_digest, "runtime": runtime},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return (
        "IndexTeam/Index-Translate-9B-q4km@sha256:"
        + hashlib.sha256(profile).hexdigest()
    )


def read_provider_lock(path: Path) -> tuple[str, dict[str, tuple[str, int]]]:
    value = _mapping(json.loads(path.read_text(encoding="utf-8")))
    if (
        value.get("schema_version") != "1.0.0"
        or value.get("status") != "SELECTED_PRODUCTION"
        or value.get("model") != "IndexTeam/Index-Translate-9B-GGUF"
        or value.get("architecture") != "qwen35"
        or value.get("license") != "Apache-2.0"
        or not isinstance(value.get("files"), list)
        or len(value["files"]) != 1
    ):
        raise RuntimeError("PROVIDER_LOCK_INVALID")
    artifact = _mapping(value["files"][0])
    if (
        artifact.get("path") != MODEL_FILE
        or type(artifact.get("size")) is not int
        or artifact["size"] <= 0
        or not isinstance(artifact.get("sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
    ):
        raise RuntimeError("PROVIDER_ARTIFACT_INVALID")
    runtime = _mapping(value.get("runtime"))
    if (
        runtime.get("repository") != "ggml-org/llama.cpp"
        or runtime.get("version") != "v0.6.0"
        or runtime.get("profile") != "index-plain-v1"
        or not re.fullmatch(r"[0-9a-f]{40}", str(runtime.get("revision", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(runtime.get("source_sha256", "")))
        or runtime.get("enable_thinking") is not False
        or runtime.get("cache_prompt") is not False
        or type(runtime.get("temperature")) not in {int, float}
        or runtime.get("temperature") != 0
    ):
        raise RuntimeError("PROVIDER_RUNTIME_INVALID")
    for key, low, high in (
        ("threads", 1, 128),
        ("context_size", 2048, 32768),
        ("output_tokens", 192, 4096),
        ("seed", 0, 2**32 - 1),
    ):
        setting = runtime.get(key)
        if type(setting) is not int or not low <= setting <= high:
            raise RuntimeError("PROVIDER_RUNTIME_INVALID")
    if runtime["output_tokens"] + 64 >= runtime["context_size"]:
        raise RuntimeError("PROVIDER_RUNTIME_INVALID")
    reference = execution_reference(artifact["sha256"], runtime)
    if value.get("execution_ref") != reference:
        raise RuntimeError("PROVIDER_EXECUTION_REF_INVALID")
    return reference, {MODEL_FILE: (artifact["sha256"], artifact["size"])}


@dataclass(frozen=True, slots=True)
class Settings:
    model_root: Path
    lock_path: Path
    socket_path: Path
    runtime_path: Path
    execution_ref: str
    artifacts: dict[str, tuple[str, int]]
    request_timeout_seconds: float = 240
    segment_timeout_seconds: float = 180
    startup_timeout_seconds: float = 600

    @classmethod
    def from_environment(cls) -> Settings:
        lock_path = Path(os.environ["AELEV_TRANSLATION_PROVIDER_LOCK_PATH"])
        reference, artifacts = read_provider_lock(lock_path)
        request_timeout = float(
            os.environ.get("AELEV_TRANSLATION_PROVIDER_REQUEST_TIMEOUT_SECONDS", "240")
        )
        segment_timeout = float(
            os.environ.get("AELEV_TRANSLATION_PROVIDER_SEGMENT_TIMEOUT_SECONDS", "180")
        )
        startup_timeout = float(
            os.environ.get("AELEV_TRANSLATION_PROVIDER_STARTUP_TIMEOUT_SECONDS", "600")
        )
        if not 0 < segment_timeout <= request_timeout <= 240:
            raise RuntimeError("PROVIDER_DEADLINE_INVALID")
        if not 0 < startup_timeout <= 1800:
            raise RuntimeError("PROVIDER_STARTUP_DEADLINE_INVALID")
        return cls(
            model_root=Path(os.environ["AELEV_TRANSLATION_PROVIDER_MODEL_ROOT"]),
            lock_path=lock_path,
            socket_path=Path(os.environ["AELEV_TRANSLATION_PROVIDER_SOCKET_PATH"]),
            runtime_path=Path(os.environ["AELEV_TRANSLATION_PROVIDER_RUNTIME_PATH"]),
            execution_ref=reference,
            artifacts=artifacts,
            request_timeout_seconds=request_timeout,
            segment_timeout_seconds=segment_timeout,
            startup_timeout_seconds=startup_timeout,
        )


def verify_model_artifacts(settings: Settings) -> None:
    if read_provider_lock(settings.lock_path) != (
        settings.execution_ref,
        settings.artifacts,
    ):
        raise RuntimeError("PROVIDER_LOCK_CHANGED")
    for name, (expected, size) in settings.artifacts.items():
        path = settings.model_root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise RuntimeError("PROVIDER_MODEL_SIZE_INVALID")
        checksum = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                checksum.update(chunk)
        if checksum.hexdigest() != expected:
            raise RuntimeError("PROVIDER_MODEL_DIGEST_INVALID")


def translation_prompt(text: str, source: str, target: str) -> str:
    return (
        f"请将以下{source}文本翻译为{target}，直接输出翻译结果，不要进行任何解释。"
        f"\n\n{text.strip()}"
    )


class TranslationEngine:
    def __init__(self, settings: Settings) -> None:
        verify_model_artifacts(settings)
        self._settings = settings
        self._profile = _mapping(json.loads(settings.lock_path.read_text())["runtime"])
        self._process: subprocess.Popen[bytes] | None = None
        self._stop_requested = False
        self._runtime_loaded = False
        self._condition = threading.Condition()
        self._tickets: deque[object] = deque()
        self._cache: OrderedDict[str, tuple[str, tuple[str, ...]]] = OrderedDict()
        self._client = httpx.Client(base_url=NATIVE_ORIGIN, trust_env=False)
        try:
            self._start_runtime()
        except Exception:
            self._client.close()
            raise

    @property
    def ready(self) -> bool:
        return (
            self._runtime_loaded
            and self._process is not None
            and self._process.poll() is None
        )

    def close(self) -> None:
        self._stop_runtime()
        self._client.close()

    def _start_runtime(self, timeout_seconds: float | None = None) -> None:
        self._runtime_loaded = False
        if not self._stop_runtime():
            raise ProviderUnavailable("PROVIDER_RUNTIME_STOP_PENDING")
        duration = self._settings.startup_timeout_seconds
        if timeout_seconds is not None:
            duration = min(duration, timeout_seconds)
        if duration <= 0:
            raise ProviderUnavailable("PROVIDER_DEADLINE_EXCEEDED")
        deadline = time.monotonic() + duration
        try:
            version = subprocess.run(
                [str(self._settings.runtime_path), "--version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=min(10, duration),
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as error:
            raise ProviderUnavailable("PROVIDER_RUNTIME_UNAVAILABLE") from error
        if self._profile["revision"] not in version.stdout + version.stderr:
            raise ProviderUnavailable("PROVIDER_RUNTIME_VERSION_MISMATCH")
        try:
            self._process = subprocess.Popen(
                [
                    str(self._settings.runtime_path),
                    "--model",
                    str(self._settings.model_root / MODEL_FILE),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8080",
                    "--alias",
                    "index-translate",
                    "--threads",
                    str(self._profile["threads"]),
                    "--threads-batch",
                    str(self._profile["threads"]),
                    "--ctx-size",
                    str(self._profile["context_size"]),
                    "--parallel",
                    "1",
                    "--cache-ram",
                    "0",
                    "--fit",
                    "off",
                    "--n-gpu-layers",
                    "0",
                    "--jinja",
                    "--chat-template-kwargs",
                    '{"enable_thinking":false}',
                    "--no-webui",
                    "--no-warmup",
                    "--log-disable",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise ProviderUnavailable("PROVIDER_RUNTIME_UNAVAILABLE") from error
        try:
            while self._process.poll() is None and time.monotonic() < deadline:
                try:
                    ready = self._client.get(
                        "/health",
                        timeout=min(1, max(0.01, deadline - time.monotonic())),
                    )
                    if ready.status_code == 200 and ready.json() == {"status": "ok"}:
                        self._runtime_loaded = True
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(min(0.1, max(0, deadline - time.monotonic())))
            raise ProviderUnavailable("PROVIDER_RUNTIME_UNAVAILABLE")
        except Exception:
            self._stop_runtime()
            raise

    def _stop_runtime(self) -> bool:
        self._runtime_loaded = False
        process = self._process
        if process is None:
            return True
        if self._stop_requested and process.poll() is None:
            return False
        try:
            if process.poll() is None:
                self._stop_requested = True
                with suppress(ProcessLookupError):
                    process.kill()
            process.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            return False
        self._process = None
        self._stop_requested = False
        return True

    @contextmanager
    def _runtime_slot(self, deadline: float) -> Generator[None]:
        ticket = object()
        with self._condition:
            self._tickets.append(ticket)
            while self._tickets[0] is not ticket:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._tickets.remove(ticket)
                    raise ProviderUnavailable("PROVIDER_DEADLINE_EXCEEDED")
                self._condition.wait(remaining)
        try:
            if time.monotonic() >= deadline:
                raise ProviderUnavailable("PROVIDER_DEADLINE_EXCEEDED")
            yield
        finally:
            with self._condition:
                self._tickets.popleft()
                self._condition.notify_all()

    def _post(
        self, route: str, payload: dict[str, object], deadline: float
    ) -> dict[str, Any]:
        remaining = min(
            self._settings.segment_timeout_seconds, deadline - time.monotonic()
        )
        if remaining <= 0:
            raise ProviderUnavailable("PROVIDER_DEADLINE_EXCEEDED")
        try:
            response = self._client.post(route, json=payload, timeout=remaining)
            response.raise_for_status()
            value: object = response.json()
            if not isinstance(value, dict):
                raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
            return cast(dict[str, Any], value)
        except httpx.TimeoutException as error:
            self._stop_runtime()
            raise ProviderUnavailable("PROVIDER_DEADLINE_EXCEEDED") from error
        except (httpx.HTTPError, ValueError) as error:
            self._stop_runtime()
            raise ProviderUnavailable("PROVIDER_RUNTIME_UNAVAILABLE") from error

    def _unit(
        self, value: str, source: str, target: str, budget: int, deadline: float
    ) -> str:
        prompt = translation_prompt(value, source, target)
        tokens_value = self._post("/tokenize", {"content": prompt}, deadline).get(
            "tokens"
        )
        tokens = (
            cast(list[object], tokens_value) if isinstance(tokens_value, list) else []
        )
        if not isinstance(tokens_value, list) or any(
            type(token) is not int for token in tokens
        ):
            raise ProviderUnavailable("PROVIDER_TOKENIZATION_INVALID")
        if len(tokens) + budget + 64 >= self._profile["context_size"]:
            return self._split_unit(value, source, target, budget, deadline)
        result = self._post(
            "/v1/chat/completions",
            {
                "model": "index-translate",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self._profile["temperature"],
                "seed": self._profile["seed"],
                "max_tokens": budget,
                "cache_prompt": self._profile["cache_prompt"],
                "chat_template_kwargs": {
                    "enable_thinking": self._profile["enable_thinking"]
                },
            },
            deadline,
        )
        choices_value = result.get("choices")
        choices = (
            cast(list[object], choices_value) if isinstance(choices_value, list) else []
        )
        if not isinstance(choices_value, list) or len(choices) != 1:
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
        choice = _mapping(choices[0])
        if choice.get("finish_reason") == "length":
            return self._split_unit(value, source, target, budget, deadline)
        if choice.get("finish_reason") != "stop":
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
        message = _mapping(choice.get("message"))
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("TRANSLATOR_EMPTY_OUTPUT")
        if message.get("reasoning_content") or re.search(
            r"<think>|<\|[^>]+\|>|^\s*(?:[a-z]{2,3})?>\s", content
        ):
            raise ProviderRequestError("TRANSLATOR_CONTROL_TOKEN_LEAK")
        return content.strip()

    def _split_unit(
        self, value: str, source: str, target: str, budget: int, deadline: float
    ) -> str:
        if len(value) < 2:
            raise ProviderUnavailable("PROVIDER_OUTPUT_LIMIT_EXCEEDED")
        middle = len(value) // 2
        boundary = value.rfind(" ", middle // 2, middle + 1)
        if boundary < 1:
            boundary = middle
        parts = (value[:boundary].strip(), value[boundary:].strip())
        return "\n".join(
            self._unit(part, source, target, budget, deadline) for part in parts if part
        )

    def translate(self, text: str, source: str, target: str) -> tuple[str, list[str]]:
        source_name = language_name(source, source=True)
        target_name = language_name(target)
        if source_name == target_name:
            return text, []
        deadline = time.monotonic() + self._settings.request_timeout_seconds
        key = json.dumps([source_name, target_name, text], ensure_ascii=False)
        with self._runtime_slot(deadline):
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached[0], list(cached[1])
            if not self.ready:
                self._start_runtime(max(0, deadline - time.monotonic()))
            result = self._unit(
                text,
                source_name,
                target_name,
                self._profile["output_tokens"],
                deadline,
            )
            warnings = ["MACHINE_TRANSLATION_UNVERIFIED"]
            if result.casefold() == text.strip().casefold():
                warnings.append("UNCHANGED_OUTPUT")
            self._cache[key] = (result, tuple(warnings))
            if len(self._cache) > 2048:
                self._cache.popitem(last=False)
        return result, warnings
