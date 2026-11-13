"""Bound authenticated request buffering before JSON parsing or inference."""

from __future__ import annotations

import asyncio

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BoundedInput:
    def __init__(
        self, app: ASGIApp, *, maximum: int = 262_144, body_timeout: float = 10
    ) -> None:
        self.app, self.maximum, self.body_timeout = app, maximum, body_timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or (scope.get("method"), scope.get("path")) != (
            "POST",
            "/v1/translate",
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        excessive = False
        try:
            async with asyncio.timeout(self.body_timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.maximum:
                        excessive = True
                        break
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await self.reject(send, 408, b"PROVIDER_REQUEST_DEADLINE_EXCEEDED")
            return
        if excessive:
            await self.reject(send, 413, b"PROVIDER_REQUEST_TOO_LARGE")
            return
        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)

    @staticmethod
    async def reject(send: Send, status: int, code: bytes) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"connection", b"close"),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b'{"detail":"' + code + b'"}'}
        )
