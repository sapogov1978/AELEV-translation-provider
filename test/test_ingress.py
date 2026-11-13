"""Streaming body bounds apply before JSON/model dispatch, without API calls."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from test_network_transport import StubEngine

from aelev_translation_provider.app import create_app
from aelev_translation_provider.ingress import BoundedInput

PAYLOAD = json.dumps(
    {
        "schema_version": "1.0.0",
        "source_language": "en",
        "target_language": "ru",
        "text": "Hello",
    }
).encode()


class Chunks(httpx.AsyncByteStream):
    def __init__(self, parts: list[bytes], delay: float = 0) -> None:
        self.parts, self.delay = parts, delay

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for part in self.parts:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield part


@pytest.mark.parametrize("claimed_size", [None, "1"])
def test_large_stream_is_rejected_before_parse_without_trusting_length(
    claimed_size: str | None,
) -> None:
    engine = StubEngine()

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app(engine)), base_url="http://opaque"
        ) as client:
            headers = {"Content-Type": "application/json"}
            if claimed_size is not None:
                headers["Content-Length"] = claimed_size
            return await client.post(
                "/v1/translate",
                content=Chunks([PAYLOAD, b" " * 262144]),
                headers=headers,
            )

    response = asyncio.run(call())
    assert response.status_code == 413
    assert response.json() == {"detail": "PROVIDER_REQUEST_TOO_LARGE"}
    assert response.headers["connection"] == "close"
    assert engine.calls == []


def test_slow_request_body_times_out_before_dispatch() -> None:
    engine = StubEngine()

    async def call() -> httpx.Response:
        app = BoundedInput(create_app(engine), body_timeout=0.02)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://opaque"
        ) as client:
            return await client.post(
                "/v1/translate",
                content=Chunks([PAYLOAD], delay=0.1),
                headers={"Content-Type": "application/json"},
            )

    response = asyncio.run(call())
    assert response.status_code == 408
    assert response.json() == {"detail": "PROVIDER_REQUEST_DEADLINE_EXCEEDED"}
    assert engine.calls == []


def test_ordinary_stream_preserves_exact_text_and_contract() -> None:
    engine = StubEngine()

    async def call() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(create_app(engine)), base_url="http://opaque"
        ) as client:
            return await client.post(
                "/v1/translate",
                content=Chunks([PAYLOAD[:10], PAYLOAD[10:]]),
                headers={"Content-Type": "application/json"},
            )

    assert asyncio.run(call()).status_code == 200
    assert engine.calls == [("Hello", "en", "ru")]
