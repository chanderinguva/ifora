"""The /scim/v2 sub-application: its own error handlers so every failure is a SCIM error (RFC 7644 3.12)."""

import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from backend.app.scim.errors import ScimError
from backend.app.scim.routes import ScimResponse, router

logger = structlog.get_logger(__name__)


def create_scim_app() -> FastAPI:
    app = FastAPI(title="IdentityForge SCIM 2.0", docs_url=None, redoc_url=None, openapi_url=None)

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

    app.include_router(router)
    return app
