"""FastAPI application and API router configuration."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import settings


async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "environment": settings.ENVIRONMENT}


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="IdentityForge API",
        description="Identity and Access Management Platform",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS: explicit origins only (credentials are allowed, so never "*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    )

    # Health check endpoint
    @app.get("/health", include_in_schema=False)
    async def health():
        """Health check endpoint."""
        return await health_check()

    # Error handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        """Handle HTTP exceptions consistently."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(SQLAlchemyError)
    async def db_exception_handler(request, exc):
        """Handle database errors."""
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal database error"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request, exc):
        """Handle validation errors."""
        return JSONResponse(
            status_code=422,
            # Drop ctx (may hold non-serialisable exceptions) and input (may echo passwords)
            content={
                "detail": [
                    {k: v for k, v in e.items() if k not in ("ctx", "input")}
                    for e in exc.errors()
                ]
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc):
        """Handle unexpected exceptions."""
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # Include auth routes (defined in backend/app/auth/routes.py)
    from backend.app.auth.routes import router as auth_router
    app.include_router(auth_router, prefix="/api/v1")

    from backend.app.audit.routes import router as audit_router
    from backend.app.auth.mfa_routes import router as mfa_router
    from backend.app.auth.passkey_routes import router as passkey_router
    from backend.app.auth.role_routes import router as role_router
    from backend.app.groups.routes import router as groups_router
    from backend.app.profiles.routes import router as profiles_router
    from backend.app.users.routes import router as users_router

    for r in (users_router, groups_router, profiles_router, audit_router, mfa_router, passkey_router, role_router):
        app.include_router(r, prefix="/api/v1")

    return app


# Create and export the app
app = create_app()