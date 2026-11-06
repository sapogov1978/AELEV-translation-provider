"""The only interface visible to Translator."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

SCHEMA_VERSION = "1.0.0"
LANGUAGE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
REQUEST_ERRORS = frozenset(
    {
        "TRANSLATOR_REQUEST_INVALID",
        "TRANSLATOR_EMPTY_OUTPUT",
        "TRANSLATOR_CONTROL_TOKEN_LEAK",
        "TRANSLATOR_UNSUPPORTED_SOURCE_LANGUAGE",
        "TRANSLATOR_UNSUPPORTED_TARGET_LANGUAGE",
    }
)
PROVIDER_ERRORS = frozenset(
    {
        "PROVIDER_DEADLINE_EXCEEDED",
        "PROVIDER_OUTPUT_LIMIT_EXCEEDED",
        "PROVIDER_RUNTIME_RESPONSE_INVALID",
        "PROVIDER_RUNTIME_STOP_PENDING",
        "PROVIDER_RUNTIME_UNAVAILABLE",
        "PROVIDER_RUNTIME_VERSION_MISMATCH",
        "PROVIDER_TOKENIZATION_INVALID",
    }
)


class ProviderRequestError(ValueError):
    """A bounded request or semantic output error safe to cross the socket."""


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    source_language: str
    target_language: str
    text: str


def parse_request(payload: object) -> TranslationRequest:
    if not isinstance(payload, dict):
        raise ProviderRequestError("TRANSLATOR_REQUEST_INVALID")
    item = cast(dict[str, object], payload)
    if (
        set(item)
        != {
            "schema_version",
            "source_language",
            "target_language",
            "text",
        }
        or item.get("schema_version") != SCHEMA_VERSION
    ):
        raise ProviderRequestError("TRANSLATOR_REQUEST_INVALID")
    source = item.get("source_language")
    target = item.get("target_language")
    text = item.get("text")
    if (
        not isinstance(source, str)
        or not LANGUAGE.fullmatch(source)
        or len(source) > 35
        or not isinstance(target, str)
        or not LANGUAGE.fullmatch(target)
        or len(target) > 35
        or not isinstance(text, str)
        or not 0 < len(text.strip()) <= 12000
    ):
        raise ProviderRequestError("TRANSLATOR_REQUEST_INVALID")
    return TranslationRequest(source, target, text)


def serialize_success(translated_text: object, warnings: object) -> dict[str, object]:
    warning_items = cast(list[object], warnings) if isinstance(warnings, list) else []
    if (
        not isinstance(translated_text, str)
        or not 0 < len(translated_text.strip()) <= 48000
        or not isinstance(warnings, list)
        or len(warning_items) > 32
        or any(
            not isinstance(item, str) or not 0 < len(item) <= 128
            for item in warning_items
        )
        or len({cast(str, item) for item in warning_items}) != len(warning_items)
    ):
        raise RuntimeError("PROVIDER_RESPONSE_INVALID")
    return {
        "schema_version": SCHEMA_VERSION,
        "translated_text": translated_text,
        "warnings": warning_items,
    }


def request_error_code(error: ProviderRequestError) -> str:
    code = str(error)
    return code if code in REQUEST_ERRORS else "TRANSLATOR_REQUEST_INVALID"


def provider_error_code(error: RuntimeError) -> str:
    code = str(error)
    return code if code in PROVIDER_ERRORS else "PROVIDER_RUNTIME_UNAVAILABLE"
