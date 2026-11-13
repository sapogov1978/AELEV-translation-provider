"""Remote translation execution owned by this opaque provider."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx

from aelev_translation_provider.contract import ProviderRequestError
from aelev_translation_provider.languages import language_name

OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
LOGGER = logging.getLogger(__name__)
PLACEHOLDER_API_KEYS = frozenset(
    {"REPLACE_WITH_OPENAI_API_KEY", "YOUR_OPENAI_API_KEY", "CHANGE_ME"}
)
TRANSLATION_FORMAT = {
    "type": "json_schema",
    "name": "translation_result",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {"translated_text": {"type": "string"}},
        "required": ["translated_text"],
        "additionalProperties": False,
    },
}


class ProviderUnavailable(RuntimeError):
    """A bounded technical failure that must remain retryable to the caller."""


def record_http_failure(response: httpx.Response) -> None:
    """Provider-local diagnostics; never log bodies, headers, keys or source text."""
    code = "UNCLASSIFIED"
    try:
        value: object = response.json() if len(response.content) <= 65536 else None
    except ValueError:
        value = None
    error = (
        cast(dict[str, object], value).get("error") if isinstance(value, dict) else None
    )
    candidate = (
        cast(dict[str, object], error).get("code") if isinstance(error, dict) else None
    )
    if candidate in (
        "insufficient_quota",
        "rate_limit_exceeded",
        "invalid_api_key",
        "model_not_found",
        "server_error",
        "context_length_exceeded",
    ):
        code = str(candidate)
    LOGGER.warning(
        "provider_upstream_failed status=%d code=%s", response.status_code, code
    )


def _mapping(value: object, code: str = "PROVIDER_LOCK_INVALID") -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(code)
    return cast(dict[str, Any], value)


def execution_reference(api: dict[str, Any], transport: dict[str, Any]) -> str:
    """Pin the requested API model, prompt and transport profile together."""
    payload = json.dumps(
        {"api": api, "transport": transport},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "openai-responses@sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    model: str
    endpoint: str
    prompt_profile: str
    prompt_sha256: str
    reasoning_effort: str
    max_output_tokens: int
    store: bool
    execution_ref: str


def read_provider_lock(path: Path, prompt_root: Path) -> ProviderProfile:
    try:
        value = _mapping(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise RuntimeError("PROVIDER_LOCK_INVALID") from error
    api = _mapping(value.get("api"))
    transport = _mapping(value.get("transport"))
    prompt_profile = api.get("prompt_profile")
    prompt_sha256 = api.get("prompt_sha256")
    if (
        value.get("schema_version") != "2.0.0"
        or value.get("status") != "SELECTED_REMOTE_API"
        or value.get("provider") != "openai"
        or api.get("endpoint") != OPENAI_RESPONSES_ENDPOINT
        or not isinstance(api.get("model"), str)
        or not re.fullmatch(r"gpt-[a-z0-9][a-z0-9.-]{1,63}", api["model"])
        or api.get("reasoning_effort") not in {"low", "medium", "high", "xhigh", "max"}
        or type(api.get("max_output_tokens")) is not int
        or not 256 <= api["max_output_tokens"] <= 128000
        or api.get("store") is not False
        or not isinstance(prompt_profile, str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", prompt_profile)
        or not isinstance(prompt_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha256)
        or transport
        != {
            "mode": "direct-https",
            "tls_verification": "system-ca",
        }
    ):
        raise RuntimeError("PROVIDER_LOCK_INVALID")
    prompt_path = prompt_root / f"{prompt_profile}.txt"
    if prompt_path.is_symlink() or not prompt_path.is_file():
        raise RuntimeError("PROVIDER_PROMPT_INVALID")
    prompt_bytes = prompt_path.read_bytes()
    if hashlib.sha256(prompt_bytes).hexdigest() != prompt_sha256:
        raise RuntimeError("PROVIDER_PROMPT_DIGEST_INVALID")
    reference = execution_reference(api, transport)
    if value.get("execution_ref") != reference:
        raise RuntimeError("PROVIDER_EXECUTION_REF_INVALID")
    return ProviderProfile(
        model=api["model"],
        endpoint=api["endpoint"],
        prompt_profile=prompt_profile,
        prompt_sha256=prompt_sha256,
        reasoning_effort=api["reasoning_effort"],
        max_output_tokens=api["max_output_tokens"],
        store=False,
        execution_ref=reference,
    )


def _api_key_from_environment() -> str:
    filename = os.environ.get("OPENAI_API_KEY_FILE", "").strip()
    key = ""
    if filename:
        path = Path(filename)
        try:
            if path.is_file():
                value = path.read_text(encoding="utf-8").strip()
                dotenv_lines = [
                    line.strip()
                    for line in value.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")
                ]
                if len(dotenv_lines) == 1 and dotenv_lines[0].startswith(
                    "OPENAI_API_KEY="
                ):
                    key = dotenv_lines[0].split("=", 1)[1].strip().strip("'\"")
                elif "\n" not in value and "\r" not in value:
                    key = value
        except OSError as error:
            raise RuntimeError("PROVIDER_CREDENTIAL_UNREADABLE") from error
    if not key:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
    if (
        not key
        or key in PLACEHOLDER_API_KEYS
        or len(key) < 20
        or any(character.isspace() for character in key)
    ):
        raise RuntimeError("PROVIDER_CREDENTIAL_UNREADABLE")
    return key


def _positive_timeout(name: str, default: str, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError as error:
        raise RuntimeError("PROVIDER_DEADLINE_INVALID") from error
    if not 0 < value <= maximum:
        raise RuntimeError("PROVIDER_DEADLINE_INVALID")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    lock_path: Path
    prompt_root: Path
    socket_path: Path
    profile: ProviderProfile
    api_key: str = field(repr=False)
    request_timeout_seconds: float = 240
    segment_timeout_seconds: float = 180

    @classmethod
    def from_environment(cls) -> Settings:
        lock_path = Path(os.environ["AELEV_TRANSLATION_PROVIDER_LOCK_PATH"])
        prompt_root = Path(os.environ["AELEV_TRANSLATION_PROVIDER_PROMPT_ROOT"])
        profile = read_provider_lock(lock_path, prompt_root)
        request_timeout = _positive_timeout(
            "AELEV_TRANSLATION_PROVIDER_REQUEST_TIMEOUT_SECONDS", "240", 240
        )
        segment_timeout = _positive_timeout(
            "AELEV_TRANSLATION_PROVIDER_SEGMENT_TIMEOUT_SECONDS", "180", 240
        )
        if segment_timeout > request_timeout:
            raise RuntimeError("PROVIDER_DEADLINE_INVALID")
        return cls(
            lock_path=lock_path,
            prompt_root=prompt_root,
            socket_path=Path(os.environ["AELEV_TRANSLATION_PROVIDER_SOCKET_PATH"]),
            profile=profile,
            api_key=_api_key_from_environment(),
            request_timeout_seconds=request_timeout,
            segment_timeout_seconds=segment_timeout,
        )


def verify_provider_configuration(lock_path: Path, prompt_root: Path) -> None:
    """Validate immutable provider inputs without requiring runtime secrets."""
    read_provider_lock(lock_path, prompt_root)


def translation_input(text: str, source_code: str, target_code: str) -> str:
    """Keep the full opaque segment and its language context as model data."""
    return json.dumps(
        {
            "source_language": {
                "code": source_code,
                "name": language_name(source_code, source=True),
            },
            "target_language": {
                "code": target_code,
                "name": language_name(target_code),
            },
            "source_text": text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


class TranslationEngine:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if (
            read_provider_lock(settings.lock_path, settings.prompt_root)
            != settings.profile
        ):
            raise RuntimeError("PROVIDER_LOCK_CHANGED")
        self._settings = settings
        self._prompt = (
            settings.prompt_root / f"{settings.profile.prompt_profile}.txt"
        ).read_text(encoding="utf-8")
        self._condition = threading.Condition()
        self._tickets: deque[object] = deque()
        self._cache: OrderedDict[str, tuple[str, tuple[str, ...]]] = OrderedDict()
        self._closed = False
        self._client = httpx.Client(trust_env=False, transport=transport)

    @property
    def ready(self) -> bool:
        """Local readiness only; no billable upstream probe is performed."""
        return not self._closed

    def close(self) -> None:
        self._closed = True
        self._client.close()

    @contextmanager
    def _execution_slot(self, deadline: float) -> Generator[None]:
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

    def _request(self, model_input: str, deadline: float) -> dict[str, Any]:
        remaining = min(
            self._settings.segment_timeout_seconds, deadline - time.monotonic()
        )
        if remaining <= 0:
            raise ProviderUnavailable("PROVIDER_DEADLINE_EXCEEDED")
        api_payload = {
            "model": self._settings.profile.model,
            "instructions": self._prompt,
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": model_input}],
                }
            ],
            "reasoning": {"effort": self._settings.profile.reasoning_effort},
            "max_output_tokens": self._settings.profile.max_output_tokens,
            "store": self._settings.profile.store,
            "text": {"format": TRANSLATION_FORMAT},
        }
        try:
            response = self._client.post(
                self._settings.profile.endpoint,
                headers={"Authorization": f"Bearer {self._settings.api_key}"},
                json=api_payload,
                timeout=remaining,
            )
        except httpx.TimeoutException as error:
            LOGGER.warning(
                "provider_upstream_failed transport=%s", type(error).__name__
            )
            raise ProviderUnavailable("PROVIDER_DEADLINE_EXCEEDED") from error
        except httpx.HTTPError as error:
            LOGGER.warning(
                "provider_upstream_failed transport=%s", type(error).__name__
            )
            raise ProviderUnavailable("PROVIDER_RUNTIME_UNAVAILABLE") from error
        if response.status_code != 200:
            record_http_failure(response)
        if response.status_code in {401, 403, 429} or response.status_code >= 500:
            raise ProviderUnavailable("PROVIDER_RUNTIME_UNAVAILABLE")
        if response.status_code != 200:
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
        try:
            value: object = response.json()
        except ValueError as error:
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID") from error
        if not isinstance(value, dict):
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
        return cast(dict[str, Any], value)

    def _translated_text(self, response: dict[str, Any]) -> str:
        if response.get("status") == "incomplete":
            raise ProviderUnavailable("PROVIDER_OUTPUT_LIMIT_EXCEEDED")
        if (
            response.get("status") != "completed"
            or response.get("model") != self._settings.profile.model
            or not isinstance(response.get("output"), list)
        ):
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
        output_texts: list[str] = []
        for raw_item in cast(list[object], response["output"]):
            item = _mapping(raw_item, "PROVIDER_RUNTIME_RESPONSE_INVALID")
            if item.get("type") == "reasoning":
                continue
            if (
                item.get("type") != "message"
                or item.get("status") != "completed"
                or not isinstance(item.get("content"), list)
            ):
                raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
            for raw_content in cast(list[object], item["content"]):
                content = _mapping(raw_content, "PROVIDER_RUNTIME_RESPONSE_INVALID")
                if content.get("type") != "output_text" or not isinstance(
                    content.get("text"), str
                ):
                    raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
                output_texts.append(content["text"])
        if len(output_texts) != 1:
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
        try:
            result = _mapping(
                json.loads(output_texts[0]), "PROVIDER_RUNTIME_RESPONSE_INVALID"
            )
        except ValueError as error:
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID") from error
        translated = result.get("translated_text")
        if set(result) != {"translated_text"} or not isinstance(translated, str):
            raise ProviderUnavailable("PROVIDER_RUNTIME_RESPONSE_INVALID")
        translated = translated.strip()
        if not translated:
            raise ProviderRequestError("TRANSLATOR_EMPTY_OUTPUT")
        if len(translated) > 48000:
            raise ProviderUnavailable("PROVIDER_OUTPUT_LIMIT_EXCEEDED")
        if re.search(r"<think>|<\|[^>]+\|>", translated):
            raise ProviderRequestError("TRANSLATOR_CONTROL_TOKEN_LEAK")
        return translated

    def translate(self, text: str, source: str, target: str) -> tuple[str, list[str]]:
        model_input = translation_input(text, source, target)
        warnings = ["MACHINE_TRANSLATION_UNVERIFIED"]
        if source == target:
            return text, [*warnings, "UNCHANGED_OUTPUT"]
        deadline = time.monotonic() + self._settings.request_timeout_seconds
        key = json.dumps(
            [self._settings.profile.execution_ref, source, target, text],
            ensure_ascii=False,
        )
        with self._execution_slot(deadline):
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached[0], list(cached[1])
            result = self._translated_text(self._request(model_input, deadline))
            if result.casefold() == text.strip().casefold():
                warnings.append("UNCHANGED_OUTPUT")
            self._cache[key] = (result, tuple(warnings))
            if len(self._cache) > 2048:
                self._cache.popitem(last=False)
        return result, warnings
