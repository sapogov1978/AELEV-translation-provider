"""Owned runtime presence is presented without domain jobs or consumer names."""

import json
from pathlib import Path
from unittest.mock import MagicMock, Mock

import httpx
import pytest
from aelev_platform_ui_client import Settings, timestamp

from translator_service import presence
from translator_service import status_publisher as owner


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("AELEV_TRANSLATOR_PRESENCE_TTL_SECONDS", "30")
    monkeypatch.setenv("AELEV_INFRASTRUCTURE_TRANSLATOR_API_CONTAINER_PORT", "8080")
    return Settings(
        "https://shell.invalid",
        "https://identity.invalid",
        "realm",
        "owner",
        "shell",
        "95779649-cefd-4c54-a65a-08f9472db1ce",
        30,
        5,
        tmp_path,
        tmp_path / "outbox.sqlite",
    )


def test_description_is_own_technical_composition(cfg: Settings) -> None:
    value = json.loads(owner.description(cfg))
    assert value["module_id"] == cfg.module_id
    assert value["revision"] == 2
    assert value["title"] == {"ru": "Перевод текстов", "en": "Text translation"}
    assert any("MADLAD" in part["title"]["ru"] for part in value["components"])
    assert value["service_kind"] == "INFRASTRUCTURE"
    assert value["sections"] == []
    assert [part["id"] for part in value["components"]] == list(owner.COMPONENTS)


@pytest.mark.parametrize("unavailable", ["none", "database", "kafka", "api", "model"])
def test_failures_never_become_false_online(
    cfg: Settings, monkeypatch: pytest.MonkeyPatch, unavailable: str
) -> None:
    repo = MagicMock()
    monkeypatch.setattr(owner, "repository", Mock(return_value=repo))
    monkeypatch.setattr(
        owner,
        "verify_kafka",
        Mock(side_effect=OSError() if unavailable == "kafka" else None),
    )
    rows = [
        {
            "id": name,
            "state": "UNKNOWN" if name == unavailable else "ONLINE",
            "observed_at": timestamp(),
        }
        for name in presence.COMPONENTS
    ]
    monkeypatch.setattr(
        owner,
        "read",
        Mock(
            side_effect=OSError() if unavailable == "database" else None,
            return_value=rows,
        ),
    )
    connection = MagicMock()
    response = connection.__enter__.return_value.get
    response.side_effect = (
        httpx.ConnectError("unreachable") if unavailable == "api" else None
    )
    response.return_value.status_code = 200
    response.return_value.json.return_value = {"status": "ok"}
    monkeypatch.setattr(httpx, "Client", Mock(return_value=connection))
    state, observations = owner.probe(cfg)
    assert state == ("ONLINE" if unavailable == "none" else "UNKNOWN")
    assert len(observations) == len(owner.COMPONENTS) - 1
    assert {part["id"] for part in observations} == set(owner.COMPONENTS) - {
        "publisher"
    }
    repo.engine.dispose.assert_called_once()
