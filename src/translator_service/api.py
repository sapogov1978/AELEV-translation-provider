"""Read-only operational API; translation remains Kafka-only."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from collections.abc import Mapping
from typing import Protocol, cast

from confluent_kafka.admin import AdminClient
from fastapi import FastAPI, HTTPException, Response

from translator_service.contracts import (
    NORMAL_REQUEST_TOPIC,
    PRIORITY_REQUEST_TOPIC,
    RESULT_TOPIC,
)
from translator_service.runtime import kafka_configuration, repository

app = FastAPI(title="AELEV translator operations", docs_url=None, redoc_url=None)


class _TopicMetadata(Protocol):
    error: object | None


class _ClusterMetadata(Protocol):
    brokers: Mapping[int, object]
    topics: Mapping[str, _TopicMetadata]


def read_status() -> dict[str, object]:
    repo = repository()
    try:
        return repo.status()
    finally:
        repo.engine.dispose()


def verify_kafka() -> None:
    metadata = cast(
        _ClusterMetadata,
        AdminClient(kafka_configuration()).list_topics(timeout=3),
    )
    if not metadata.brokers:
        raise RuntimeError("TRANSLATOR_KAFKA_BROKER_UNAVAILABLE")
    required = {
        PRIORITY_REQUEST_TOPIC,
        NORMAL_REQUEST_TOPIC,
        RESULT_TOPIC,
    }
    missing = required.difference(metadata.topics)
    if missing:
        raise RuntimeError(f"TRANSLATOR_TOPICS_UNAVAILABLE:{','.join(sorted(missing))}")
    unavailable = sorted(
        name for name in required if metadata.topics[name].error is not None
    )
    if unavailable:
        raise RuntimeError(f"TRANSLATOR_TOPICS_UNAVAILABLE:{','.join(unavailable)}")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def ready() -> dict[str, str]:
    try:
        read_status()
        verify_kafka()
    except Exception as error:
        raise HTTPException(status_code=503, detail="not ready") from error
    return {"status": "ready"}


@app.get("/v1/status")
def status() -> dict[str, object]:
    return read_status()


@app.get("/metrics", response_class=Response)
def metrics() -> Response:
    state = read_status()
    jobs = cast(dict[str, int], state["jobs"])
    lines = ["# TYPE aelev_translator_jobs gauge"]
    for key, value in sorted(jobs.items()):
        state, queue = key.split(":")
        lines.append(
            f'aelev_translator_jobs{{state="{state}",queue="{queue}"}} {value}'
        )
    return Response("\n".join(lines) + "\n", media_type="text/plain")
