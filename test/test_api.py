"""Operational readiness includes the mandatory Kafka dependency."""

import pytest
from fastapi import HTTPException

from translator_service import api


def test_ready_requires_database_and_kafka(monkeypatch: pytest.MonkeyPatch) -> None:
    checked: list[str] = []

    def database_ready() -> dict[str, object]:
        checked.append("database")
        return {}

    monkeypatch.setattr(api, "read_status", database_ready)
    monkeypatch.setattr(api, "verify_kafka", lambda: checked.append("kafka"))

    assert api.ready() == {"status": "ready"}
    assert checked == ["database", "kafka"]


def test_ready_fails_when_kafka_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def database_ready() -> dict[str, object]:
        return {}

    monkeypatch.setattr(api, "read_status", database_ready)

    def unavailable() -> None:
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(api, "verify_kafka", unavailable)
    with pytest.raises(HTTPException) as error:
        api.ready()
    assert error.value.status_code == 503
    assert error.value.detail == "not ready"
