"""Test configuration and fixtures for IdentityForge backend."""

import os
import pytest
import tempfile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

from backend.app.db import Base
from backend.app.main import app

# Use a temporary database for tests
TEST_DATABASE_PATH = tempfile.mktemp(suffix=".db")
TEST_DATABASE_URL = f"sqlite:///{TEST_DATABASE_PATH}"

engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session")
def test_app():
    """Create test application."""
    app.config["TESTING"] = True
    return app


@pytest.fixture
def db_session():
    """Create database session for tests."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_app, db_session):
    """Create test client."""
    from starlette.testclient import TestClient

    def get_db_override():
        try:
            yield db_session
        finally:
            pass

    test_app.dependency_overrides = {"get_db": get_db_override}
    return TestClient(test_app)