"""Durable inbox, fenced leases and immutable replayable results."""

import json
import uuid
from typing import Any

from sqlalchemy import create_engine, text

from translator_service.contracts import digest, parse, result_bytes
from translator_service.schema import verify_schema


class Repository:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(
            url,
            pool_size=2,
            max_overflow=2,
            pool_timeout=5,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"options": "-c statement_timeout=5000 -c lock_timeout=1000"},
        )
        verify_schema(self.engine)

    def accept(self, raw: bytes) -> None:
        event = parse(raw, "TranslationRequested")
        request_id = event["data"]["request_id"]
        with self.engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO translation_job(request_id,request_digest,payload)
                VALUES(:id,:digest,:raw) ON CONFLICT DO NOTHING"""),
                {"id": request_id, "digest": digest(raw), "raw": raw},
            )
            row = (
                connection.execute(
                    text("""SELECT request_digest,state FROM translation_job
                WHERE request_id=:id FOR UPDATE"""),
                    {"id": request_id},
                )
                .mappings()
                .one()
            )
            if row["request_digest"] != digest(raw):
                raise ValueError("TRANSLATION_REQUEST_ID_CONFLICT")
            if row["state"] in {"SUCCEEDED", "FAILED"}:
                connection.execute(
                    text("""UPDATE translation_outbox SET state='PENDING'
                    WHERE request_id=:id"""),
                    {"id": request_id},
                )

    def lease(self) -> dict[str, Any] | None:
        token = str(uuid.uuid4())
        with self.engine.begin() as connection:
            if (
                connection.execute(
                    text("SELECT desired_state FROM translation_control FOR SHARE")
                ).scalar_one()
                != "RUNNING"
            ):
                return None
            row = (
                connection.execute(
                    text("""SELECT request_id,payload,request_digest
                FROM translation_job WHERE
                (state='PENDING' AND available_at<=now()
                 OR state='RUNNING' AND lease_until<=now())
                AND EXISTS(SELECT 1 FROM translation_control
                           WHERE desired_state='RUNNING')
                ORDER BY available_at,created_at,request_id
                FOR UPDATE SKIP LOCKED LIMIT 1""")
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            connection.execute(
                text("""UPDATE translation_job SET state='RUNNING',
                lease_token=:token,lease_until=now()+interval '360 seconds',
                attempt_count=attempt_count+1
                WHERE request_id=:id"""),
                {"id": row["request_id"], "token": token},
            )
            return {**row, "token": token}

    def complete(self, lease: dict[str, Any], response: dict[str, Any]) -> bool:
        raw = result_bytes(
            json.loads(lease["payload"]), lease["request_digest"], response
        )
        with self.engine.begin() as connection:
            changed = connection.execute(
                text("""UPDATE translation_job SET state=:state,
                result=:raw, completed_at=now(),lease_token=NULL,lease_until=NULL,
                error_code=:error
                WHERE request_id=:id AND state='RUNNING'
                AND lease_token=:token AND lease_until>now()
                RETURNING request_id"""),
                {
                    "id": lease["request_id"],
                    "token": lease["token"],
                    "state": response["status"],
                    "error": response["error_code"] or None,
                    "raw": raw,
                },
            ).first()
            if changed is None:
                return False
            connection.execute(
                text("""INSERT INTO translation_outbox(request_id,payload)
                VALUES(:id,:raw)"""),
                {"id": lease["request_id"], "raw": raw},
            )
            return True

    def retry(
        self, lease: dict[str, Any], error_code: str = "TRANSLATOR_UNAVAILABLE"
    ) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""UPDATE translation_job SET state='PENDING',
                lease_token=NULL,lease_until=NULL,
                available_at=now()+interval '30 seconds',error_code=:error
                WHERE request_id=:id AND state='RUNNING' AND lease_token=:token"""),
                {
                    "id": lease["request_id"],
                    "token": lease["token"],
                    "error": error_code,
                },
            )

    def quarantine(self, identity: str, raw: bytes, error: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""INSERT INTO translation_quarantine(identity,payload,error_code)
                VALUES(:id,:raw,:error) ON CONFLICT DO NOTHING"""),
                {"id": identity, "raw": raw, "error": error},
            )

    def pending(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in (
                    connection.execute(
                        text("""SELECT request_id,payload FROM translation_outbox
                WHERE state='PENDING' ORDER BY request_id LIMIT 25""")
                    ).mappings()
                )
            ]

    def published(self, identity: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("""UPDATE translation_outbox SET state='PUBLISHED',
                published_at=now(),attempt_count=attempt_count+1
                WHERE request_id=:id"""),
                {"id": identity},
            )

    def control(
        self,
        action: str,
        *,
        command_id: str,
        actor: str,
        expected_revision: int,
        rationale: str,
    ) -> int:
        if (
            action not in {"PAUSE", "RESUME", "RESET"}
            or not command_id
            or not actor
            or not rationale
        ):
            raise ValueError("TRANSLATOR_CONTROL_INVALID")
        with self.engine.begin() as connection:
            current = connection.execute(
                text("SELECT revision FROM translation_control FOR UPDATE")
            ).scalar_one()
            previous = (
                connection.execute(
                    text(
                        "SELECT * FROM translation_control_command WHERE command_id=:id"
                    ),
                    {"id": command_id},
                )
                .mappings()
                .first()
            )
            if previous:
                if any(
                    previous[key] != value
                    for key, value in {
                        "actor": actor,
                        "action": action,
                        "expected_revision": expected_revision,
                        "rationale": rationale,
                    }.items()
                ):
                    raise ValueError("TRANSLATOR_COMMAND_ID_CONFLICT")
                return previous["resulting_revision"]
            if current != expected_revision:
                raise ValueError("TRANSLATOR_CONTROL_REVISION_CONFLICT")
            if action == "RESET":
                if connection.execute(
                    text(
                        "SELECT count(*) FROM translation_job "
                        "WHERE state='RUNNING' AND lease_until>now()"
                    )
                ).scalar_one():
                    raise ValueError("TRANSLATOR_CONTROL_DRAIN_REQUIRED")
                connection.execute(
                    text("""UPDATE translation_job SET state='PENDING',
                    available_at=now(),lease_token=NULL,lease_until=NULL
                    WHERE state IN ('PENDING','RUNNING')""")
                )
            revision = current + 1
            connection.execute(
                text(
                    "UPDATE translation_control "
                    "SET desired_state=:state,revision=:revision"
                ),
                {
                    "state": "PAUSED" if action == "PAUSE" else "RUNNING",
                    "revision": revision,
                },
            )
            connection.execute(
                text("""INSERT INTO translation_control_command
                (command_id,actor,action,expected_revision,resulting_revision,rationale)
                VALUES(:id,:actor,:action,:expected,:result,:rationale)"""),
                {
                    "id": command_id,
                    "actor": actor,
                    "action": action,
                    "expected": expected_revision,
                    "result": revision,
                    "rationale": rationale,
                },
            )
            return revision
