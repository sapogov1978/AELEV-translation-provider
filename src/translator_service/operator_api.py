"""Self-hosted documentation for the existing read-only operational API."""

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.routing import APIRoute

from translator_service.api import app as internal_app

ASSETS = Path(__file__).resolve().parents[2] / "swagger-assets"
app = FastAPI(title="AELEV translator operations", docs_url=None, redoc_url=None)
app.router.routes.extend(
    route for route in internal_app.routes if isinstance(route, APIRoute)
)


@app.middleware("http")
async def protect_response(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers.update(
        {
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store",
        }
    )
    return response


@app.get("/docs", include_in_schema=False)
def documentation() -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>AELEV translator operations — Swagger</title>"
        '<link rel="stylesheet" href="/docs/assets/swagger-ui.css"></head>'
        '<body><div id="swagger-ui"></div>'
        '<script src="/docs/assets/swagger-ui-bundle.js"></script>'
        '<script src="/docs/init.js"></script></body></html>'
    )


@app.get("/docs/init.js", include_in_schema=False)
def initialize_documentation() -> Response:
    return Response(
        'window.ui=SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui",'
        "deepLinking:true,validatorUrl:null,persistAuthorization:false});",
        media_type="application/javascript",
    )


@app.get("/docs/assets/swagger-ui-bundle.js", include_in_schema=False)
def javascript() -> FileResponse:
    return FileResponse(ASSETS / "swagger-ui-bundle.js", media_type="text/javascript")


@app.get("/docs/assets/swagger-ui.css", include_in_schema=False)
def stylesheet() -> FileResponse:
    return FileResponse(ASSETS / "swagger-ui.css", media_type="text/css")
