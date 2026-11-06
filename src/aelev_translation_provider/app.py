"""Provider-owned Unix-socket HTTP application."""

from __future__ import annotations

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


class Engine(Protocol):
    @property
    def ready(self) -> bool: ...

    def translate(
        self, text: str, source: str, target: str
    ) -> tuple[str, list[str]]: ...


def create_app(engine: Engine) -> FastAPI:
    app = FastAPI(
        title="AELEV opaque translation provider",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        if not engine.ready:
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
