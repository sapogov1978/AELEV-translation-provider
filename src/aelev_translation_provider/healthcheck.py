"""Image-owned readiness probe over the private Unix socket."""

from __future__ import annotations

import http.client
import json
import os
import socket


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=4)
        self._path = path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(self._path)
        self.sock = connection


def main() -> None:
    path = os.environ.get(
        "AELEV_TRANSLATION_PROVIDER_SOCKET_PATH",
        "/run/aelev-translator/translator.sock",
    )
    connection = UnixHTTPConnection(path)
    try:
        connection.request("GET", "/healthz", headers={"Host": "translation-provider"})
        response = connection.getresponse()
        body = response.read(1024)
        if response.status != 200 or json.loads(body) != {"status": "ok"}:
            raise SystemExit(1)
    except (OSError, ValueError, http.client.HTTPException):
        raise SystemExit(1) from None
    finally:
        connection.close()


if __name__ == "__main__":
    main()
