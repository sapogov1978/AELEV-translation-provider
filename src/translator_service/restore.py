"""Read-only integrity checks for an isolated restored translator database."""

from sqlalchemy import text

from translator_service.contracts import digest, parse
from translator_service.repository import Repository


def verify(repo: Repository) -> dict[str, object]:
    count = 0
    with repo.engine.connect() as connection:
        connection = connection.execution_options(isolation_level="REPEATABLE READ")
        connection.execute(text("SET TRANSACTION READ ONLY"))
        statement = text("SELECT * FROM translation_job").execution_options(
            stream_results=True, yield_per=100
        )
        for row in connection.execute(statement).mappings():
            event = parse(bytes(row["payload"]), "TranslationRequested")
            if (
                digest(bytes(row["payload"])) != row["request_digest"]
                or event["data"]["request_id"] != row["request_id"]
            ):
                raise ValueError("TRANSLATOR_RESTORE_REQUEST_MISMATCH")
            if row["state"] in {"SUCCEEDED", "FAILED"}:
                result = parse(bytes(row["result"]), "TranslationCompleted")
                if (
                    result["data"]["request_digest"] != row["request_digest"]
                    or result["data"]["status"] != row["state"]
                    or result["causationid"] != event["id"]
                    or result["correlationid"] != event["correlationid"]
                    or result["traceparent"] != event["traceparent"]
                    or any(
                        result["data"][key] != event["data"][key]
                        for key in (
                            "request_id",
                            "translator_ref",
                            "source_language",
                            "target_language",
                            "source_digest",
                        )
                    )
                ):
                    raise ValueError("TRANSLATOR_RESTORE_RESULT_MISMATCH")
                saved = connection.execute(
                    text("SELECT payload FROM translation_outbox WHERE request_id=:id"),
                    {"id": row["request_id"]},
                ).scalar_one()
                if bytes(saved) != bytes(row["result"]):
                    raise ValueError("TRANSLATOR_RESTORE_OUTBOX_MISMATCH")
            count += 1
    return {"status": "VERIFIED", "jobs": count}
