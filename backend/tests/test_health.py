"""Health check endpoint tests."""

import pytest
from fastapi.testclient import TestClient


def test_health_endpoint(client: TestClient):
    """Test health check endpoint returns healthy status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "healthy"


def test_swagger_endpoint(client: TestClient):
    """Test OpenAPI documentation is accessible."""
    response = client.get("/docs")
    assert response.status_code == 200


def test_openapi_endpoint(client: TestClient):
    """Test OpenAPI schema is accessible."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert data["title"] == "IdentityForge API"