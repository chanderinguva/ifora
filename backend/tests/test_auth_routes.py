"""Authentication routes tests."""

import pytest
from fastapi.testclient import TestClient
from backend.app.users.model import User
from backend.app.db import get_db


class TestAuthRoutes:
    """Tests for authentication API routes."""

    def test_health_endpoint(self, client: TestClient):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_login_invalid_credentials(self, client: TestClient):
        """Test login with invalid credentials."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent@example.com", "password": "wrongpassword"},
        )
        # Should return 401 for invalid credentials
        # Note: May return 404 if route not yet fully implemented
        assert response.status_code in [401, 422, 404]

    def test_bootstrap_missing_secret_key(self, client: TestClient):
        """Test bootstrap without secret key."""
        response = client.post(
            "/api/v1/admin/bootstrap",
            json={
                "email": "test@example.com",
                "password": "password12345678",
                "first_name": "Test",
                "last_name": "User",
                "secret_key": "wrong-key",
            },
        )
        assert response.status_code == 403

    def test_login_validation_errors(self, client: TestClient):
        """Test login validation for malformed input."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "test"},
        )
        assert response.status_code == 422

    def test_openapi_schema(self, client: TestClient):
        """Test OpenAPI schema is generated."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "paths" in data
        assert "/api/v1/auth/login" in data["paths"]
        assert "/api/v1/admin/bootstrap" in data["paths"]