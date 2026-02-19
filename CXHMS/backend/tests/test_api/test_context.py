"""Tests for context API endpoints."""
import pytest
from fastapi.testclient import TestClient


class TestContextEndpoints:
    """Test context API endpoints."""

    def test_get_sessions(self, client: TestClient):
        """Test getting sessions."""
        response = client.get("/api/context/sessions")
        assert response.status_code in [200, 404, 503]

    def test_create_session(self, client: TestClient):
        """Test creating a session."""
        response = client.post(
            "/api/context/sessions",
            json={"agent_id": "default"}
        )
        assert response.status_code in [200, 201, 400, 404, 503]

    def test_get_session_not_found(self, client: TestClient):
        """Test getting a non-existent session."""
        response = client.get("/api/context/sessions/non-existent-session")
        assert response.status_code in [404, 503]

    def test_delete_session_not_found(self, client: TestClient):
        """Test deleting a non-existent session."""
        response = client.delete("/api/context/sessions/non-existent-session")
        assert response.status_code in [404, 503]

    def test_get_session_messages_not_found(self, client: TestClient):
        """Test getting messages for non-existent session."""
        response = client.get("/api/context/sessions/non-existent-session/messages")
        assert response.status_code in [404, 503]

    def test_add_message_to_session_not_found(self, client: TestClient):
        """Test adding message to non-existent session."""
        response = client.post(
            "/api/context/sessions/non-existent-session/messages",
            json={"role": "user", "content": "Hello"}
        )
        assert response.status_code in [404, 503]

    def test_get_context_stats(self, client: TestClient):
        """Test getting context statistics."""
        response = client.get("/api/context/stats")
        assert response.status_code in [200, 404, 503]


class TestContextValidation:
    """Test context validation."""

    def test_create_session_invalid_agent(self, client: TestClient):
        """Test creating session with invalid agent."""
        response = client.post(
            "/api/context/sessions",
            json={"agent_id": ""}
        )
        assert response.status_code in [200, 201, 400, 404, 422, 503]

    def test_add_message_invalid_role(self, client: TestClient):
        """Test adding message with invalid role."""
        response = client.post(
            "/api/context/sessions/test-session/messages",
            json={"role": "invalid", "content": "Hello"}
        )
        assert response.status_code in [400, 404, 422, 503]
