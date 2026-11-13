"""Image-owned local readiness; no upstream inference or TLS key is needed."""

from __future__ import annotations

import http.client
import json
import math
import os
import socket
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

HEALTH_FILE = Path("/tmp/aelev-translation-provider-readiness.json")


def record_readiness(ready: bool) -> None:
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=HEALTH_FILE.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        json.dump(
            {"ready": ready, "pid": os.getpid(), "observed_at": time.monotonic()},
            stream,
        )
    try:
        temporary.replace(HEALTH_FILE)
    finally:
        temporary.unlink(missing_ok=True)


def clear_readiness() -> None:
    HEALTH_FILE.unlink(missing_ok=True)


def healthy() -> bool:
    try:
        if HEALTH_FILE.is_symlink():
            return False
        with HEALTH_FILE.open("rb") as stream:
            raw = stream.read(1025)
        value: object = json.loads(raw)
        if len(raw) > 1024 or not isinstance(value, dict):
            return False
        record = cast(dict[str, object], value)
        pid, observed = record.get("pid"), record.get("observed_at")
        if (
            set(record) != {"ready", "pid", "observed_at"}
            or record.get("ready") is not True
            or type(pid) is not int
            or not 0 < pid <= 2_147_483_647
            or isinstance(observed, bool)
            or not isinstance(observed, int | float)
            or not math.isfinite(observed)
            or not 0 <= time.monotonic() - observed <= 5
        ):
            return False
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


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
    if os.path.lexists(HEALTH_FILE):
        raise SystemExit(0 if healthy() else 1)
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
