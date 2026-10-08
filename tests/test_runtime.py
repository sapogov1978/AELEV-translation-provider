"""Transport commit ordering and failed publication regression checks."""

import sys
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from translator_service import runtime


def test_database_outage_never_commits_or_polls_next_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions: list[str] = []

    class Engine:
        def dispose(self) -> None:
            actions.append("dispose")

    class Repo:
        engine = Engine()

        def accept(self, raw: bytes) -> None:
            assert raw == b"request"
            raise OperationalError("not logged", {}, Exception("not logged"))

    class Message:
        def error(self) -> None:
            return None

        def value(self) -> bytes:
            return b"request"

    class Consumer:
        def __init__(self, config: dict[str, Any]) -> None:
            del config

        def subscribe(self, topics: list[str]) -> None:
            assert topics == [runtime.REQUEST_TOPIC]

        def poll(self, timeout: float) -> Message:
            del timeout
            actions.append("poll")
            return Message()

        def commit(self, **kwargs: Any) -> None:
            del kwargs
            actions.append("commit")

        def close(self) -> None:
            actions.append("close")

    monkeypatch.setattr(runtime, "repository", lambda: Repo())
    monkeypatch.setattr(runtime, "Consumer", Consumer)

    def configuration() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(runtime, "kafka_configuration", configuration)
    monkeypatch.setattr(sys, "argv", ["test", "consumer"])
    with pytest.raises(RuntimeError, match="STORAGE_UNAVAILABLE"):
        runtime.main()
    assert actions == ["poll", "close", "dispose"]
