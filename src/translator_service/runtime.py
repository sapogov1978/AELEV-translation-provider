"""Independent Kafka consumer, bounded model worker and durable outbox."""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from typing import Any

import httpx
from confluent_kafka import Consumer, KafkaError, Producer
from jsonschema import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from translator_service.contracts import RESULT_TOPIC
from translator_service.environment import database_sslmode, database_url
from translator_service.repository import Repository

LOGGER = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = {"level": record.levelname, "event": record.getMessage()}
        for key in (
            "request_id",
            "correlationid",
            "traceparent",
            "duration_ms",
            "outcome",
            "actor_digest",
            "queue",
        ):
            if hasattr(record, key):
                fields[key] = getattr(record, key)
        return json.dumps(fields, sort_keys=True)


def kafka_configuration() -> dict[str, Any]:
    config = {
        "bootstrap.servers": os.environ["AELEV_KAFKA_BOOTSTRAP_SERVERS"],
        "client.id": "translator-service-" + os.environ.get("HOSTNAME", "local"),
    }
    security = os.environ.get("AELEV_KAFKA_SECURITY_PROTOCOL", "SSL")
    local = os.environ.get("AELEV_ENVIRONMENT", "production") == "local"
    if security not in {"SSL", "PLAINTEXT"} or (not local and security != "SSL"):
        raise RuntimeError("TRANSLATOR_KAFKA_TRANSPORT_INVALID")
    config["security.protocol"] = security
    if security == "SSL":
        for target, source in {
            "ssl.ca.location": "AELEV_KAFKA_CA_FILE",
            "ssl.certificate.location": "AELEV_KAFKA_CLIENT_CERT_FILE",
            "ssl.key.location": "AELEV_KAFKA_CLIENT_KEY_FILE",
        }.items():
            filename = os.environ[source]
            if (
                filename == "NONE"
                or not filename
                or os.path.basename(filename) != filename
            ):
                raise RuntimeError("TRANSLATOR_KAFKA_IDENTITY_MISSING")
            config[target] = os.path.join(
                os.environ["AELEV_TRANSLATOR_SECRET_ROOT"], filename
            )
    return config


def repository() -> Repository:
    if os.environ.get(
        "AELEV_ENVIRONMENT", "production"
    ) != "local" and database_sslmode() not in {
        "require",
        "verify-ca",
        "verify-full",
    }:
        raise RuntimeError("TRANSLATOR_DATABASE_TLS_REQUIRED")
    return Repository(database_url())


def compute(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "1.0.0",
        **{
            key: data[key]
            for key in ("translator_ref", "source_language", "target_language")
        },
    }
    if data["operation"] == "PROFILE_UNIT":
        payload["profile"] = {
            "subject_area": data["text"],
            "positive_terms": [],
            "excluded_terms": [],
            "excluded_topics": [],
        }
        route = "/v1/localize-profile"
    else:
        payload.update({"text": data["text"], "source_digest": data["source_digest"]})
        route = (
            "/v1/translate-evidence"
            if data["operation"] == "OPERATOR_REVIEW"
            else "/v1/translate-text"
        )
    with httpx.Client(
        transport=httpx.HTTPTransport(uds=os.environ["AELEV_TRANSLATOR_SOCKET_PATH"]),
        base_url="http://private-model",
        trust_env=False,
        timeout=240,
    ) as client:
        response = client.post(route, json=payload)
    if response.status_code == 422:
        code = response.json().get("detail", "TRANSLATOR_REQUEST_INVALID")
        permitted = {
            "TRANSLATOR_EMPTY_OUTPUT",
            "TRANSLATOR_CONTROL_TOKEN_LEAK",
            "TRANSLATOR_UNSUPPORTED_TARGET_LANGUAGE",
            "TRANSLATOR_UNSUPPORTED_SOURCE_LANGUAGE",
            "TRANSLATOR_VERSION_MISMATCH",
        }
        return {
            "status": "FAILED",
            "translated_text": "",
            "warnings": [],
            "error_code": code if code in permitted else "TRANSLATOR_REQUEST_INVALID",
        }
    response.raise_for_status()
    result = response.json()
    for key in (
        "schema_version",
        "translator_ref",
        "source_language",
        "target_language",
    ):
        if result.get(key) != payload[key]:
            raise RuntimeError("TRANSLATOR_PRIVATE_RESPONSE_INVALID")
    translated = (
        result["profile"]["subject_area"]
        if data["operation"] == "PROFILE_UNIT"
        else result["translated_text"]
    )
    if (
        not isinstance(translated, str)
        or not translated.strip()
        or len(translated) > 48000
    ):
        raise RuntimeError("TRANSLATOR_PRIVATE_RESPONSE_INVALID")
    return {
        "status": "SUCCEEDED",
        "translated_text": translated,
        "warnings": result.get("warnings", []),
        "error_code": "",
    }


def publish_once(repo: Repository, producer: Producer) -> None:
    for row in repo.pending():
        failures: list[KafkaError | None] = []

        def delivered(
            error: KafkaError | None,
            _message: Any,
            collected: list[KafkaError | None] = failures,
        ) -> None:
            collected.append(error)

        producer.produce(
            RESULT_TOPIC,
            key=row["request_id"].encode(),
            value=bytes(row["payload"]),
            on_delivery=delivered,
        )
        outstanding = producer.flush(10)
        if outstanding or len(failures) != 1 or failures[0] is not None:
            raise RuntimeError("TRANSLATOR_KAFKA_PUBLISH_FAILED")
        repo.published(row["request_id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "role",
        choices=(
            "consumer",
            "worker",
            "outbox",
            "health",
            "status",
            "control",
            "verify-restored-state",
        ),
    )
    parser.add_argument("--action", choices=("PAUSE", "RESUME", "RESET"))
    parser.add_argument("--command-id")
    parser.add_argument("--actor")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--rationale")
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    repo = repository()
    if args.role in {"health", "status"}:
        if args.role == "status":
            sys.stdout.write(json.dumps(repo.status()))
        return
    if args.role == "control":
        sys.stdout.write(
            json.dumps(
                {
                    "revision": repo.control(
                        args.action,
                        command_id=args.command_id,
                        actor=args.actor,
                        expected_revision=args.expected_revision,
                        rationale=args.rationale,
                    )
                }
            )
        )
        return
    if args.role == "verify-restored-state":
        from translator_service.restore import verify

        sys.stdout.write(json.dumps(verify(repo)))
        return
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda _sig, _frame: stopped.set())
    client: Any = None
    if args.role == "consumer":
        client = Consumer(
            {
                **kafka_configuration(),
                "group.id": os.environ["AELEV_TRANSLATOR_KAFKA_GROUP"],
                "enable.auto.commit": False,
                "auto.offset.reset": "earliest",
                "isolation.level": "read_committed",
            }
        )
        client.subscribe([os.environ["AELEV_TRANSLATOR_REQUEST_TOPIC"]])
    if args.role == "outbox":
        client = Producer(
            {**kafka_configuration(), "enable.idempotence": True, "acks": "all"}
        )
    from translator_service.presence import start

    presence_thread = start(repo.engine, args.role, stopped)
    try:
        while not stopped.is_set():
            try:
                if args.role == "consumer":
                    message = client.poll(1)
                    if message is None:
                        continue
                    if message.error():
                        if message.error().code() == KafkaError._PARTITION_EOF:
                            continue
                        raise RuntimeError("TRANSLATOR_KAFKA_READ_FAILED")
                    raw = message.value() or b""
                    try:
                        repo.accept(
                            raw, int(os.environ["AELEV_TRANSLATOR_REQUEST_PRIORITY"])
                        )
                    except (ValueError, ValidationError):
                        repo.quarantine(
                            f"{message.topic()}:{message.partition()}:{message.offset()}",
                            raw,
                            "TRANSLATION_CONTRACT_INVALID",
                        )
                    client.commit(message=message, asynchronous=False)
                elif args.role == "outbox":
                    publish_once(repo, client)
                    stopped.wait(1)
                else:
                    lease = repo.lease(
                        int(os.environ["AELEV_TRANSLATOR_HIGH_PRIORITY_BURST"])
                    )
                    if lease is None:
                        stopped.wait(1)
                        continue
                    started = time.perf_counter()
                    try:
                        result = compute(json.loads(lease["payload"])["data"])
                        if not repo.complete(lease, result):
                            LOGGER.warning("translation_stale_lease")
                            continue
                        envelope = json.loads(lease["payload"])
                        LOGGER.info(
                            "translation_completed",
                            extra={
                                "request_id": lease["request_id"],
                                "correlationid": envelope["correlationid"],
                                "traceparent": envelope["traceparent"],
                                "outcome": result["status"],
                                "duration_ms": round(
                                    1000 * (time.perf_counter() - started)
                                ),
                            },
                        )
                    except (httpx.HTTPError, RuntimeError, ValueError, ValidationError):
                        repo.retry(lease)
                        LOGGER.warning("translation_model_retry")
            except SQLAlchemyError:
                if args.role == "consumer":
                    # Do not poll past an unpersisted record: restart from the
                    # last committed Kafka offset after the storage outage.
                    raise RuntimeError("TRANSLATOR_STORAGE_UNAVAILABLE") from None
                LOGGER.warning("translation_storage_retry")
                stopped.wait(5)
    finally:
        stopped.set()
        presence_thread.join(timeout=10)
        if args.role == "consumer":
            client.close()
        repo.engine.dispose()


if __name__ == "__main__":
    main()
