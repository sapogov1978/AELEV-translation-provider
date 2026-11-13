"""Provider-owned opaque HTTP application."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Protocol

from fastapi import Body, FastAPI, HTTPException

from aelev_translation_provider.contract import (
    ProviderRequestError,
    parse_request,
    provider_error_code,
    request_error_code,
    serialize_success,
)
from aelev_translation_provider.engine import ProviderUnavailable
from aelev_translation_provider.healthcheck import clear_readiness, record_readiness
from aelev_translation_provider.ingress import BoundedInput


class Engine(Protocol):
    @property
    def ready(self) -> bool: ...

    def translate(
        self, text: str, source: str, target: str
    ) -> tuple[str, list[str]]: ...


def create_app(engine: Engine, readiness: Callable[[], bool] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        async def observe() -> None:
            while True:
                if readiness is not None:
                    record_readiness(engine.ready and readiness())
                await asyncio.sleep(1)

        observer = asyncio.create_task(observe()) if readiness is not None else None
        try:
            yield
        finally:
            if observer is not None:
                observer.cancel()
                with suppress(asyncio.CancelledError):
                    await observer
                clear_readiness()

    app = FastAPI(
        title="AELEV opaque translation provider",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(BoundedInput)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        if not engine.ready or (readiness is not None and not readiness()):
            raise HTTPException(status_code=503, detail="PROVIDER_NOT_READY")
        return {"status": "ok"}

    @app.post("/v1/translate")
    def translate(payload: Annotated[object, Body()]) -> dict[str, object]:
        try:
            request = parse_request(payload)
            translated, warnings = engine.translate(
                request.text, request.source_language, request.target_language
            )
            return serialize_success(translated, warnings)
        except ProviderRequestError as error:
            raise HTTPException(
                status_code=422, detail=request_error_code(error)
            ) from error
        except ProviderUnavailable as error:
            raise HTTPException(
                status_code=503, detail=provider_error_code(error)
            ) from error
        except RuntimeError as error:
            raise HTTPException(
                status_code=503, detail=provider_error_code(error)
            ) from error

    return app
