"""One lifecycle for private HTTP diagnostics and operator HTTPS/mTLS."""

from __future__ import annotations

import asyncio
import os
import signal
import ssl
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from aelev_platform_ui_client import https_url

PREFIX = "AELEV_INFRASTRUCTURE_TRANSLATOR_"


def swagger_url() -> str:
    """Return the owner's browser-routable HTTPS documentation address."""
    value = https_url(os.environ[PREFIX + "API_PUBLIC_URL"])
    parsed = urlsplit(value)
    if (
        parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or "\x7f" in value
    ):
        raise ValueError("TRANSLATOR_API_PUBLIC_URL_REQUIRES_ORIGIN")
    return value.rstrip("/") + "/docs"


def configurations() -> tuple[uvicorn.Config, uvicorn.Config]:
    """Validate TLS before either listener starts; never fall back to plaintext."""
    swagger_url()
    if os.environ[PREFIX + "API_BIND_ADDRESS"] not in {"127.0.0.1", "::1"}:
        raise ValueError("TRANSLATOR_PRIVATE_API_REQUIRES_LOOPBACK_BIND")
    internal_port = int(os.environ[PREFIX + "API_CONTAINER_PORT"])
    operator_port = int(os.environ[PREFIX + "API_HTTPS_CONTAINER_PORT"])
    if internal_port == operator_port:
        raise ValueError("TRANSLATOR_API_LISTENERS_REQUIRE_DISTINCT_PORTS")
    tls = Path("/run/secrets/translator-api")
    internal = uvicorn.Config(
        "translator_service.api:app",
        host="0.0.0.0",
        port=internal_port,
        proxy_headers=False,
        access_log=False,
    )
    operator = uvicorn.Config(
        "translator_service.operator_api:app",
        host="0.0.0.0",
        port=operator_port,
        ssl_certfile=str(tls / "server.crt"),
        ssl_keyfile=str(tls / "server.key"),
        ssl_ca_certs=str(tls / "clients-ca.crt"),
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        proxy_headers=False,
        access_log=False,
    )
    operator.load()
    assert isinstance(operator.ssl, ssl.SSLContext)
    operator.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    return internal, operator


class Server(uvicorn.Server):
    """The enclosing process handles signals for both listeners together."""

    @contextmanager
    def capture_signals(self) -> Generator[None]:
        yield


async def serve(servers: tuple[Server, Server]) -> None:
    """Stop both listeners on a signal, failure or unexpected listener exit."""
    stopped = False

    def shutdown() -> None:
        nonlocal stopped
        stopped = True
        for server in servers:
            server.should_exit = True

    loop = asyncio.get_running_loop()
    for value in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(value, shutdown)
    tasks = [asyncio.create_task(server.serve()) for server in servers]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        unexpected = not stopped
        shutdown()
        await asyncio.gather(*tasks)
        if unexpected:
            raise RuntimeError("TRANSLATOR_API_LISTENER_STOPPED")
    finally:
        shutdown()
        await asyncio.gather(*tasks, return_exceptions=True)
        for value in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(value)


if __name__ == "__main__":
    private, public = configurations()
    asyncio.run(serve((Server(private), Server(public))))
