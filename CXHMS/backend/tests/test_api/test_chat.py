"""Chat API endpoint tests."""

import pytest
from fastapi.testclient import TestClient


class TestChatEndpoints:
    """Test chat API endpoints."""

    def test_send_message_validation(self, client: TestClient):
        """Test sending a message without message field returns 422."""
        response = client.post("/api/chat", json={"agent_id": "default"})
        assert response.status_code == 422

    def test_send_message_with_message(self, client: TestClient):
        """Test sending a message with message field."""
        response = client.post("/api/chat", json={"message": "Hello", "agent_id": "default"})
        assert response.status_code in [200, 503]

    def test_send_message_with_session(self, client: TestClient):
        """Test sending a message with session_id."""
        response = client.post(
            "/api/chat",
            json={"message": "Hello", "session_id": "test-session", "agent_id": "default"},
        )
        assert response.status_code in [200, 503]

    def test_send_message_with_all_fields(self, client: TestClient):
        """Test sending a message with all fields."""
        response = client.post(
            "/api/chat",
            json={
                "message": "Hello, how are you?",
                "session_id": "test-session-123",
                "agent_id": "default",
            },
        )
        assert response.status_code in [200, 503]

    def test_get_chat_history(self, client: TestClient):
        """Test getting chat history for a session."""
        response = client.get("/api/chat/history/non-existent-session")
        assert response.status_code in [200, 404, 503]

    def test_get_chat_history_response_structure(self, client: TestClient):
        """Test response structure for chat history."""
        response = client.get("/api/chat/history/test-session")
        if response.status_code == 200:
            data = response.json()
            assert "messages" in data or isinstance(data, list)

    def test_stream_chat_validation(self, client: TestClient):
        """Test streaming chat endpoint validation."""
        response = client.post("/api/chat/stream", json={"agent_id": "default"})
        assert response.status_code == 422

    def test_stream_chat_with_message(self, client: TestClient):
        """Test streaming chat with message."""
        response = client.post(
            "/api/chat/stream",
            json={"message": "Hello", "session_id": "test-session", "agent_id": "default"},
        )
        assert response.status_code in [200, 503]


class TestChatSessionEndpoints:
    """Test chat session endpoints."""

    def test_get_sessions(self, client: TestClient):
        """Test getting all sessions."""
        response = client.get("/api/context/sessions")
        assert response.status_code in [200, 503]

    def test_get_sessions_response_structure(self, client: TestClient):
        """Test response structure for sessions."""
        response = client.get("/api/context/sessions")
        if response.status_code == 200:
            data = response.json()
            assert "sessions" in data or isinstance(data, list)

    def test_create_session(self, client: TestClient):
        """Test creating a new session."""
        response = client.post("/api/context/sessions", json={"title": "New Chat"})
        assert response.status_code in [200, 201, 503]

    def test_create_session_minimal(self, client: TestClient):
        """Test creating a session with minimal data."""
        response = client.post("/api/context/sessions", json={})
        assert response.status_code in [200, 201, 503]

    def test_delete_session(self, client: TestClient):
        """Test deleting a session."""
        response = client.delete("/api/context/sessions/non-existent-session")
        assert response.status_code in [200, 404, 503]


class TestChatEndpointsContentType:
    """Test content type for chat endpoints."""

    def test_send_message_content_type(self, client: TestClient):
        """Test content type for send message."""
        response = client.post("/api/chat", json={"message": "Hello"})
        if response.status_code == 200:
            assert "application/json" in response.headers.get("content-type", "")

    def test_get_sessions_content_type(self, client: TestClient):
        """Test content type for get sessions."""
        response = client.get("/api/context/sessions")
        if response.status_code == 200:
            assert "application/json" in response.headers.get("content-type", "")


class TestChatValidation:
    """Test validation for chat endpoints."""

    def test_send_message_empty_message(self, client: TestClient):
        """Test sending empty message."""
        response = client.post("/api/chat", json={"message": ""})
        assert response.status_code in [422, 200, 503]

    def test_send_message_very_long_message(self, client: TestClient):
        """Test sending very long message."""
        long_message = "a" * 10000
        response = client.post("/api/chat", json={"message": long_message})
        assert response.status_code in [200, 413, 503]

    def test_send_message_special_characters(self, client: TestClient):
        """Test sending message with special characters."""
        response = client.post("/api/chat", json={"message": "Hello! @#$%^&*() 你好 🎉"})
        assert response.status_code in [200, 503]
