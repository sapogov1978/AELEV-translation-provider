"""Repository tests use only an explicitly isolated PostgreSQL database."""

import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from translator_service.contracts import digest, parse
from translator_service.repository import Repository
from translator_service.restore import verify


def request(*, value: str = "central bank", identity: str | None = None) -> bytes:
    identity = identity or str(uuid.uuid4())
    timestamp = datetime.now(UTC).isoformat()
    event: dict[str, object] = {
        "specversion": "1.0",
        "id": identity,
        "source": "urn:aelev:test-client",
        "type": "com.aelev.translation-requested.v1",
        "time": timestamp,
        "subject": "translation/" + identity,
        "datacontenttype": "application/json",
        "dataschema": "https://schemas.aelev.dev/events/v1#/$defs/TranslationRequested",
        "correlationid": identity,
        "causationid": identity,
        "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
        "data": {
            "schema_version": "1.0.0",
            "recorded_at": timestamp,
            "provenance": {
                "owner_context": "TEST_CLIENT",
                "producer_id": "test-client",
                "producer_version": "0.1.0",
                "input_refs": [],
            },
            "request_id": identity,
            "operation": "TRANSLATE_TEXT",
            "text": value,
            "source_digest": digest(value.encode()),
            "source_language": "en",
            "target_language": "de",
            "translator_ref": "google/madlad400-3b-mt-q4k@sha256:" + "a" * 64,
        },
    }
    return json.dumps(event, ensure_ascii=False, sort_keys=True).encode()


@pytest.fixture
def repo() -> Iterator[Repository]:
    url = os.environ.get("AELEV_TRANSLATOR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("isolated PostgreSQL URL not configured")
    # Require an explicitly named disposable database, not a working service DB.
    if "/translator_test" not in url:
        raise ValueError("test database must be named translator_test")
    repo = Repository(url)
    with repo.engine.begin() as connection:
        connection.execute(text("TRUNCATE translation_job CASCADE"))
        connection.execute(text("TRUNCATE translation_control_command"))
        connection.execute(
            text("UPDATE translation_control SET revision=1, desired_state='RUNNING'")
        )
    yield repo
    repo.engine.dispose()


def success() -> dict[str, Any]:
    return {
        "status": "SUCCEEDED",
        "translated_text": "Zentralbank",
        "warnings": [],
        "error_code": "",
    }


def test_request_contract_and_digest_are_checked() -> None:
    raw = request()
    assert parse(raw, "TranslationRequested")["data"]["text"] == "central bank"
    event = json.loads(raw)
    event["data"]["text"] = "changed"
    with pytest.raises(ValueError, match="DIGEST"):
        parse(json.dumps(event).encode(), "TranslationRequested")


def test_contract_accepts_an_independent_technical_client() -> None:
    event = json.loads(request())
    event["source"] = "urn:aelev:another-client"
    event["data"]["provenance"]["owner_context"] = "ANOTHER_CLIENT"
    event["data"]["provenance"]["producer_id"] = "another-client"
    assert parse(json.dumps(event).encode(), "TranslationRequested")["source"] == (
        "urn:aelev:another-client"
    )


def test_duplicate_computes_once_and_replays_exact_saved_result(
    repo: Repository,
) -> None:
    raw = request()
    repo.accept(raw)
    repo.accept(raw)
    lease = repo.lease()
    assert lease is not None
    assert repo.lease() is None
    assert repo.complete(lease, success())
    original = bytes(repo.pending()[0]["payload"])
    repo.published(lease["request_id"])
    assert repo.pending() == []
    repo.accept(raw)
    assert repo.lease() is None
    assert bytes(repo.pending()[0]["payload"]) == original
    assert verify(repo) == {"status": "VERIFIED", "jobs": 1}


def test_request_id_collision_preserves_original(repo: Repository) -> None:
    raw = request()
    repo.accept(raw)
    event = json.loads(raw)
    event["data"]["text"] = "monetary policy"
    event["data"]["source_digest"] = digest(b"monetary policy")
    with pytest.raises(ValueError, match="ID_CONFLICT"):
        repo.accept(json.dumps(event).encode())
    lease = repo.lease()
    assert lease is not None and bytes(lease["payload"]) == raw


def test_operator_result_requires_exact_request_and_outbox_ack(
    repo: Repository,
) -> None:
    raw = request()
    identity = parse(raw, "TranslationRequested")["id"]
    repo.accept(raw)
    lease = repo.lease()
    assert lease is not None
    assert repo.complete(lease, success())
    assert repo.delivered_result(identity, digest(raw)) is None
    repo.published(identity)
    result = repo.delivered_result(identity, digest(raw))
    assert result is not None
    assert (
        parse(result, "TranslationCompleted")["data"]["translated_text"]
        == "Zentralbank"
    )
    assert repo.delivered_result(identity, digest(b"foreign")) is None


def test_slow_retry_does_not_starve_older_waiting_work(repo: Repository) -> None:
    first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
    repo.accept(request(identity=first_id))
    first = repo.lease()
    assert first is not None
    repo.retry(first)
    repo.accept(request(identity=second_id, value="monetary policy"))
    with repo.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE translation_job SET available_at=clock_timestamp() "
                "WHERE request_id=:id"
            ),
            {"id": first_id},
        )
    second = repo.lease()
    assert second is not None and second["request_id"] == second_id


def test_priority_burst_always_releases_normal_work(repo: Repository) -> None:
    normal_id = str(uuid.uuid4())
    repo.accept(request(identity=normal_id), priority=100)
    priority_ids = [str(uuid.uuid4()) for _ in range(3)]
    for identity in priority_ids:
        repo.accept(request(identity=identity), priority=0)
    first = repo.lease(high_priority_burst=2)
    second = repo.lease(high_priority_burst=2)
    third = repo.lease(high_priority_burst=2)
    assert first is not None and first["request_id"] in priority_ids
    assert second is not None and second["request_id"] in priority_ids
    assert third is not None and third["request_id"] == normal_id


def test_restore_rejects_valid_but_mismatched_result_lineage(repo: Repository) -> None:
    repo.accept(request())
    lease = repo.lease()
    assert lease is not None and repo.complete(lease, success())
    result = json.loads(bytes(repo.pending()[0]["payload"]))
    result["data"]["target_language"] = "fr"
    changed = json.dumps(result).encode()
    parse(changed, "TranslationCompleted")
    with repo.engine.begin() as connection:
        connection.execute(
            text("UPDATE translation_job SET result=:raw"), {"raw": changed}
        )
        connection.execute(
            text("UPDATE translation_outbox SET payload=:raw"), {"raw": changed}
        )
    with pytest.raises(ValueError, match="RESTORE_RESULT_MISMATCH"):
        verify(repo)


def test_expired_lease_fences_old_result_and_retry_never_cancels(
    repo: Repository,
) -> None:
    repo.accept(request())
    first = repo.lease()
    assert first is not None
    with repo.engine.begin() as connection:
        connection.execute(
            text("UPDATE translation_job SET lease_until=now()-interval '1 second'")
        )
    second = repo.lease()
    assert second is not None and second["token"] != first["token"]
    assert not repo.complete(first, success())
    repo.retry(first)
    repo.retry(second)
    assert repo.lease() is None
    with repo.engine.begin() as connection:
        row = connection.execute(
            text("SELECT state,attempt_count FROM translation_job")
        ).one()
        assert row == ("PENDING", 2)
        connection.execute(text("UPDATE translation_job SET available_at=now()"))
    third = repo.lease()
    assert third is not None and repo.complete(third, success())


def test_pause_reset_preserves_complete_and_command_history(repo: Repository) -> None:
    repo.accept(request())
    lease = repo.lease()
    assert lease is not None
    assert (
        repo.control(
            "PAUSE",
            command_id="pause",
            actor="operator",
            expected_revision=1,
            rationale="maintenance",
        )
        == 2
    )
    assert repo.lease() is None
    with pytest.raises(ValueError, match="DRAIN_REQUIRED"):
        repo.control(
            "RESET",
            command_id="reset",
            actor="operator",
            expected_revision=2,
            rationale="retry",
        )
    assert repo.complete(lease, success())
    repo.accept(request(value="finance"))
    assert (
        repo.control(
            "RESET",
            command_id="reset",
            actor="operator",
            expected_revision=2,
            rationale="retry",
        )
        == 3
    )
    assert (
        repo.control(
            "RESET",
            command_id="reset",
            actor="operator",
            expected_revision=2,
            rationale="retry",
        )
        == 3
    )
    with pytest.raises(ValueError, match="ID_CONFLICT"):
        repo.control(
            "PAUSE",
            command_id="reset",
            actor="operator",
            expected_revision=2,
            rationale="retry",
        )
    assert len(repo.pending()) == 1
    assert repo.lease() is not None


def test_invalid_completion_rolls_back_and_original_remains_leased(
    repo: Repository,
) -> None:
    repo.accept(request())
    lease = repo.lease()
    assert lease is not None
    with pytest.raises(ValueError, match="RESULT_INVALID"):
        repo.complete(lease, {**success(), "translated_text": ""})
    assert repo.pending() == []
    assert repo.complete(lease, success())
