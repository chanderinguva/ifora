"""Database configuration and SQLAlchemy setup."""

import logging
import os
from typing import AsyncGenerator

from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ["DATABASE_URL"]  # required; no credential defaults

DATABASE_URL_ASYNC = os.environ["DATABASE_URL_ASYNC"]

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
AsyncEngine = create_async_engine(DATABASE_URL_ASYNC, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = sessionmaker(
    class_=AsyncSession, expire_on_commit=False, bind=AsyncEngine
)

# Shared declarative base for all models
Base = declarative_base()


def init_db():
    """Initialize database tables.

    This function imports all models to register them with the Base metadata
    before creating the tables.
    """
    # Import all models to register them with Base

    # Now create all tables
    Base.metadata.create_all(bind=engine)


def get_db(request: Request):
    """Get database session (FastAPI dependency).

    Returns a SQLAlchemy session that is automatically closed after the request.
    """
    from backend.app.tenancy import TenantNotResolved, resolve_tenant_id, use_tenant

    try:
        tenant_id = resolve_tenant_id(request.headers.get("host"))
    except TenantNotResolved:
        raise HTTPException(status_code=404, detail="Not found")  # same answer for unknown and missing: no tenant oracle
    except Exception:
        logger.exception("tenant resolution failed")  # a resolver fault must not fall back to another tenant
        raise HTTPException(status_code=503, detail="Service temporarily unavailable")
    db = use_tenant(SessionLocal(), tenant_id)
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session."""
    async with AsyncSessionLocal() as session:
        yield session