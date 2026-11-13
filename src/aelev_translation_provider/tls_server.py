"""Reloadable mTLS and exact-peer admission before the opaque ASGI app."""

from __future__ import annotations

import asyncio
import ssl
from typing import Any, cast

import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol

from .tls_identity import Identity, IdentityError, leaf_certificate, peer_matches


class IdentityConfig(uvicorn.Config):
    @property
    def is_ssl(self) -> bool:
        return bool(getattr(self, "ssl", None)) or super().is_ssl


def configured_server(
    app: Any, identity: Identity, host: str, port: int
) -> uvicorn.Server:
    class ExactPeerProtocol(H11Protocol):
        def connection_made(self, transport: asyncio.Transport) -> None:
            self.allowed_peer = False
            super().connection_made(transport)
            peer = transport.get_extra_info("peercert")
            if not isinstance(peer, dict):
                transport.close()
                return
            certificate = cast(dict[str, Any], peer)
            session = transport.get_extra_info("ssl_object")
            if not isinstance(session, ssl.SSLObject):
                transport.close()
                return
            raw = session.getpeercert(binary_form=True)
            if (
                not isinstance(raw, bytes)
                or not leaf_certificate(ssl.DER_cert_to_PEM_cert(raw).encode("ascii"))
                or not peer_matches(certificate, identity.peer_id)
            ):
                transport.close()
                return
            self.allowed_peer = True
            original = self.app
            admitted_context = session.context

            async def guarded(scope: Any, receive: Any, send: Any) -> None:
                try:
                    current_trust = identity.current() is admitted_context
                except IdentityError:
                    current_trust = False
                if not current_trust or not peer_matches(certificate, identity.peer_id):
                    await send(
                        {
                            "type": "http.response.start",
                            "status": 503,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"connection", b"close"),
                            ],
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": b'{"detail":"PROVIDER_TLS_IDENTITY_UNAVAILABLE"}',
                        }
                    )
                    return
                await original(scope, receive, send)

            self.app = guarded

        def data_received(self, data: bytes) -> None:
            if not self.allowed_peer:
                self.transport.close()
                return
            super().data_received(data)

    config = IdentityConfig(
        app,
        host=host,
        port=port,
        http=ExactPeerProtocol,
        ws="none",
        access_log=False,
        proxy_headers=False,
        log_level="warning",
        limit_concurrency=32,
    )
    config.load()
    config.ssl = identity.wire_context()
    return uvicorn.Server(config)
