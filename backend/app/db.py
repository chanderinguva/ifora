"""Database configuration and SQLAlchemy setup."""

import os
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

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


def get_db():
    """Get database session (FastAPI dependency).

    Returns a SQLAlchemy session that is automatically closed after the request.
    """
    from backend.app.tenancy import use_tenant, default_tenant_id

    db = use_tenant(SessionLocal(), default_tenant_id())  # single-tenant: resolved per request later (host/path)
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session."""
    async with AsyncSessionLocal() as session:
        yield session