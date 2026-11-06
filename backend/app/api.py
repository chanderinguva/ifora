"""FastAPI application and API router configuration."""

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError

from backend.app.config import settings


async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "environment": settings.ENVIRONMENT}


def get_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="IdentityForge API",
        description="Identity and Access Management Platform",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Custom route class to handle trailing slashes
    class TrailingSlashRoute(APIRoute):
        def get_route_path(self) -> str:
            if self.path.endswith("/") and not self.path == "/":
                return self.path[:-1]
            return self.path

    app.router.route_class = TrailingSlashRoute

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
            content={"detail": exc.errors()},
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

    return app


app = get_app()