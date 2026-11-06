"""Test configuration and fixtures for IdentityForge backend."""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def test_app():
    """Create test application."""
    from backend.app.api import get_app

    app = get_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def mock_db_session():
    """Mock database session for unit tests."""
    class MockSession:
        def __init__(self):
            self.committed = False
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        def commit(self):
            self.committed = True

        def close(self):
            pass

        def query(self, model):
            return MockQuery()

    class MockQuery:
        def __init__(self):
            pass

        def filter(self, *args):
            return self

        def first(self):
            return None

    return MockSession()


@pytest.fixture
def client(test_app, mock_db_session):
    """Create test client."""
    from starlette.testclient import TestClient
    from unittest.mock import patch

    with patch("backend.app.db.get_db", return_value=mock_db_session):
        return TestClient(test_app)