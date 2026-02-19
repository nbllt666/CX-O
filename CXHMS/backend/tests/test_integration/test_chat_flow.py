"""Chat flow integration tests."""

import pytest
from fastapi.testclient import TestClient


class TestChatFlow:
    """Test complete chat flows."""

    def test_health_before_chat(self, client: TestClient):
        """Test health check before attempting chat."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_chat_endpoints_exist(self, client: TestClient):
        """Test that chat endpoints exist and return expected status codes."""
        # Test chat endpoint
        response = client.post("/api/chat", json={})
        assert response.status_code in [422, 500, 503]

        # Test stream endpoint
        response = client.post("/api/chat/stream", json={})
        assert response.status_code in [422, 500, 503]

        # Test history endpoint
        response = client.get("/api/chat/history/test-session")
        assert response.status_code in [200, 404, 500, 503]

    def test_agent_endpoints_exist(self, client: TestClient):
        """Test that agent endpoints exist."""
        response = client.get("/api/agents")
        assert response.status_code in [200, 503]

    def test_memory_endpoints_exist(self, client: TestClient):
        """Test that memory endpoints exist."""
        response = client.get("/api/memories")
        assert response.status_code in [200, 503]

    def test_api_documentation_accessible(self, client: TestClient):
        """Test API documentation is accessible."""
        response = client.get("/docs")
        assert response.status_code == 200

        response = client.get("/redoc")
        assert response.status_code == 200

    def test_openapi_schema(self, client: TestClient):
        """Test OpenAPI schema is available."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        assert "openapi" in data
        assert "paths" in data
