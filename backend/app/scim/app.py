"""The /scim/v2 sub-application: its own error handlers so every failure is a SCIM error (RFC 7644 3.12)."""

import json

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from backend.app.scim import projection
from backend.app.scim.errors import ScimError
from backend.app.scim.routes import ScimResponse, router

logger = structlog.get_logger(__name__)


def create_scim_app() -> FastAPI:
    app = FastAPI(title="Ifora SCIM 2.0", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(ScimError)
    async def scim_error(request, exc: ScimError):
        return ScimResponse(exc.body(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):  # also Starlette's 404/405 and the shared rate limiter's 429
        return ScimResponse(
            ScimError(exc.status_code, str(exc.detail) if exc.status_code != 404 else "Resource not found").body(),
            status_code=exc.status_code, headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return ScimResponse(ScimError(400, "Invalid request", "invalidSyntax").body(), status_code=400)  # never echo input

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request, exc):
        logger.error("scim.db_error", error=type(exc).__name__)
        return ScimResponse(ScimError(500, "Internal server error").body(), status_code=500)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.error("scim.unexpected", error=type(exc).__name__)
        return ScimResponse(ScimError(500, "Internal server error").body(), status_code=500)

    @app.middleware("http")
    async def shape_response(request, call_next):
        """`attributes` / `excludedAttributes` apply to every Users and Groups response (RFC 7644 3.4.2.5, 3.9)."""
        q = request.query_params
        if "attributes" not in q and "excludedAttributes" not in q:
            return await call_next(request)
        attrs, excl = projection.parse(q.get("attributes")), projection.parse(q.get("excludedAttributes"))
        resp = await call_next(request)
        if resp.status_code >= 300 or resp.status_code == 204:
            return resp
        raw = b"".join([chunk async for chunk in resp.body_iterator])
        try:
            body = projection.apply(json.loads(raw), attrs, excl)
        except ScimError as e:
            return ScimResponse(e.body(), status_code=e.status)
        except ValueError:
            body = None
        if body is None:
            return ScimResponse(json.loads(raw), status_code=resp.status_code)
        headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "content-type")}
        return ScimResponse(body, status_code=resp.status_code, headers=headers)

    app.include_router(router)
    return app
