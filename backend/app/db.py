"""Database configuration and SQLAlchemy setup."""

import os
from contextlib import contextmanager
from typing import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://identityforge:identityforge_local_password_change_after_first_login@localhost:5432/identityforge",
)

DATABASE_URL_ASYNC = os.environ.get(
    "DATABASE_URL_ASYNC",
    "postgresql+asyncpg://identityforge:identityforge_local_password_change_after_first_login@localhost:5432/identityforge",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
AsyncEngine = create_async_engine(DATABASE_URL_ASYNC, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = sessionmaker(
    class_=AsyncSession, expire_on_commit=False, bind=AsyncEngine
)

Base = declarative_base()


def init_db():
    """Initialize database tables."""
    from backend.app.users.model import User
    from backend.app.groups.model import Group
    from backend.app.audit.model import AuditEvent

    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db():
    """Get database session context manager."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Get async database session."""
    async with AsyncSessionLocal() as session:
        yield session