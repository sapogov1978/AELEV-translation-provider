"""Check transport commit ordering and failed-publication recovery."""

import json
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError

from translator_service import presence, runtime, topic_provisioner


@pytest.mark.parametrize("version", ["1.0.0", "2.0.0"])
def test_execution_duration_measures_only_compute_and_preserves_v1(
    monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    compute = Mock(return_value={"status": "SUCCEEDED"})
    monkeypatch.setattr(runtime, "compute", compute)
    monkeypatch.setattr(
        runtime.time, "perf_counter", Mock(side_effect=[50000, 50001.25])
    )
    response, duration_ms = runtime.execute_translation(
        {
            "payload": json.dumps({"data": {"schema_version": version}}).encode(),
            "execution_ref": "owner-only",
        }
    )
    assert duration_ms == 1250
    compute.assert_called_once_with({"schema_version": version}, "owner-only")
    assert ("execution_duration_ms" in response) == (version == "2.0.0")
    if version == "2.0.0":
        assert response["execution_duration_ms"] == 1250


def test_topic_retention_is_declared_by_translator_not_broker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parameters = {
        "RETENTION_MS": "604800000",
        "RETENTION_BYTES": "-1",
        "MAX_MESSAGE_BYTES": "1048576",
        "MIN_INSYNC_REPLICAS": "1",
    }
    for key, value in parameters.items():
        monkeypatch.setenv("AELEV_TRANSLATOR_TOPIC_" + key, value)
    expected = {
        "cleanup.policy": "delete",
        "retention.ms": "604800000",
        "retention.bytes": "-1",
        "max.message.bytes": "1048576",
        "min.insync.replicas": "1",
    }
    topics = topic_provisioner.required_topics()
    assert set(topics) == {
        "translation.requests.priority.v1",
        "translation.requests.v1",
        "translation.results.v1",
        "translation.requests.v2",
        "translation.requests.priority.v2",
        "translation.results.v2",
    }
    assert all(configuration == expected for configuration in topics.values())


def test_database_outage_never_commits_or_polls_next_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actions: list[str] = []

    class Engine:
        def dispose(self) -> None:
            actions.append("dispose")

    class Repo:
        engine = Engine()

        def accept(self, raw: bytes, priority: int) -> None:
            assert raw == b"request"
            assert priority == 0
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
            assert topics == [
                "translation.requests.priority.v1",
                "translation.requests.priority.v2",
            ]

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
    monkeypatch.setattr(presence, "start", Mock(return_value=Mock()))
    monkeypatch.setattr(runtime, "Consumer", Consumer)

    def configuration() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(runtime, "kafka_configuration", configuration)
    monkeypatch.setenv("AELEV_TRANSLATOR_KAFKA_GROUP", "test-priority")
    monkeypatch.setenv(
        "AELEV_TRANSLATOR_REQUEST_TOPIC", "translation.requests.priority.v1"
    )
    monkeypatch.setenv("AELEV_TRANSLATOR_REQUEST_PRIORITY", "0")
    monkeypatch.setattr(sys, "argv", ["test", "consumer"])
    with pytest.raises(RuntimeError, match="STORAGE_UNAVAILABLE"):
        runtime.main()
    assert actions == ["poll", "close", "dispose"]


def test_existing_topics_are_verified_without_empty_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names = ["translation.requests.v1"]
    parameters = {"cleanup.policy": "delete", "retention.ms": "42"}
    checked: list[str] = []

    class Future:
        def result(self, timeout: float) -> dict[str, SimpleNamespace]:
            assert timeout > 0
            return {
                key: SimpleNamespace(value=value) for key, value in parameters.items()
            }

    class Admin:
        def list_topics(self, timeout: float) -> SimpleNamespace:
            assert timeout > 0
            return SimpleNamespace(
                topics={
                    name: SimpleNamespace(partitions={0: SimpleNamespace(replicas=[1])})
                    for name in names
                }
            )

        def create_topics(self, topics: list[object]) -> None:
            raise AssertionError(
                "existing topics must not call create_topics, even with []"
            )

        def describe_configs(self, resources: list[Any]) -> dict[Any, Future]:
            checked.extend(resource.name for resource in resources)
            return {resource: Future() for resource in resources}

    def admin_factory(config: dict[str, Any]) -> Admin:
        assert config == {}
        return Admin()

    def configuration() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(topic_provisioner, "AdminClient", admin_factory)
    monkeypatch.setattr(topic_provisioner, "kafka_configuration", configuration)
    monkeypatch.setattr(
        topic_provisioner,
        "required_topics",
        lambda: {name: dict(parameters) for name in names},
    )
    monkeypatch.setenv("AELEV_TRANSLATOR_TOPIC_PARTITIONS", "1")
    monkeypatch.setenv("AELEV_TRANSLATOR_TOPIC_REPLICATION_FACTOR", "1")
    topic_provisioner.main()
    assert checked == names
