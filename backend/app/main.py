"""Main entry point for the IdentityForge backend application."""

import logging
import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from backend.app import api

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer() if __debug__ else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("application.starting", app="identityforge-api")

    # Initialize database
    try:
        from backend.app.db import init_db
        init_db()
        logger.info("database.initialized")
    except Exception as e:
        logger.error("database.initialization.failed", error=str(e))
        sys.exit(1)

    yield

    logger.info("application.stopped", app="identityforge-api")


def create_app() -> FastAPI:
    """Create the application with lifespan management."""
    app = FastAPI(
        title="IdentityForge API",
        description="Identity and Access Management Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Mount API router
    app.include_router(api.app.router, prefix="/api/v1")

    return app


# Create application instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)