"""Health check endpoint tests."""

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health_check(self, client: TestClient):
        """Test basic health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] in ["healthy", "degraded"]
        assert "version" in data
        assert "components" in data

    def test_health_check_content_type(self, client: TestClient):
        """Test health check returns correct content type."""
        response = client.get("/health")
        assert response.headers["content-type"] == "application/json"

    def test_health_check_method_not_allowed(self, client: TestClient):
        """Test health check only accepts GET."""
        response = client.post("/health")
        assert response.status_code == 405

    def test_root_endpoint(self, client: TestClient):
        """Test root path returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "service" in data
        assert data["service"] == "CXHMS"
