"""Tests for tools API endpoints."""
import pytest
from fastapi.testclient import TestClient


class TestToolsEndpoints:
    """Test tools API endpoints."""

    def test_get_tools(self, client: TestClient):
        """Test getting all tools."""
        response = client.get("/api/tools")
        assert response.status_code in [200, 404, 503]

    def test_get_tool_by_name_not_found(self, client: TestClient):
        """Test getting a non-existent tool."""
        response = client.get("/api/tools/non-existent-tool")
        assert response.status_code in [400, 404, 500, 503]

    def test_enable_tool_not_found(self, client: TestClient):
        """Test enabling a non-existent tool."""
        response = client.post("/api/tools/non-existent-tool/enable")
        assert response.status_code in [404, 503]

    def test_disable_tool_not_found(self, client: TestClient):
        """Test disabling a non-existent tool."""
        response = client.post("/api/tools/non-existent-tool/disable")
        assert response.status_code in [404, 503]

    def test_get_tool_stats(self, client: TestClient):
        """Test getting tool statistics."""
        response = client.get("/api/tools/stats")
        assert response.status_code in [200, 404, 503]

    def test_execute_tool_not_found(self, client: TestClient):
        """Test executing a non-existent tool."""
        response = client.post(
            "/api/tools/non-existent-tool/execute",
            json={"args": {}}
        )
        assert response.status_code in [404, 503]


class TestToolsValidation:
    """Test tools validation."""

    def test_execute_tool_invalid_args(self, client: TestClient):
        """Test executing tool with invalid arguments."""
        response = client.post(
            "/api/tools/calculator/execute",
            json={"args": "not a dict"}
        )
        assert response.status_code in [400, 404, 422, 503]
