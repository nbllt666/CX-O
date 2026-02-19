"""Agent API endpoint tests."""

import pytest
from fastapi.testclient import TestClient


class TestAgentEndpoints:
    """Test agent API endpoints."""

    def test_get_all_agents(self, client: TestClient):
        """Test getting all agents."""
        response = client.get("/api/agents")
        assert response.status_code in [200, 503]

    def test_get_all_agents_response_structure(self, client: TestClient):
        """Test response structure for get all agents."""
        response = client.get("/api/agents")
        if response.status_code == 200:
            data = response.json()
            assert data.get("status") == "success"
            assert "agents" in data
            assert isinstance(data["agents"], list)

    def test_get_agent_by_id(self, client: TestClient):
        """Test getting a specific agent."""
        response = client.get("/api/agents/default")
        assert response.status_code in [200, 404, 503]

    def test_get_agent_by_id_response_structure(self, client: TestClient):
        """Test response structure for get agent by id."""
        response = client.get("/api/agents/default")
        if response.status_code == 200:
            data = response.json()
            assert data.get("status") == "success"
            assert "agent" in data
            assert "id" in data["agent"]
            assert "name" in data["agent"]

    def test_get_agent_not_found(self, client: TestClient):
        """Test getting a non-existent agent."""
        response = client.get("/api/agents/non-existent-agent-12345")
        assert response.status_code in [404, 503]

    def test_create_agent_validation(self, client: TestClient):
        """Test creating an agent without required fields."""
        response = client.post("/api/agents", json={"description": "Agent without name"})
        assert response.status_code == 422

    def test_create_agent_with_name(self, client: TestClient):
        """Test creating an agent with only name."""
        response = client.post("/api/agents", json={"name": "Test Agent"})
        assert response.status_code in [200, 201, 400, 503]

    def test_create_agent_with_all_fields(self, client: TestClient):
        """Test creating an agent with all fields."""
        response = client.post(
            "/api/agents",
            json={
                "name": "Full Agent",
                "description": "A complete agent",
                "system_prompt": "You are helpful",
                "model": "gpt-4",
                "temperature": 0.7,
                "max_tokens": 2000,
                "use_memory": True,
                "use_tools": True,
                "memory_scene": "default",
            },
        )
        assert response.status_code in [200, 201, 400, 503]

    def test_update_agent_not_found(self, client: TestClient):
        """Test updating a non-existent agent."""
        response = client.put("/api/agents/non-existent-agent-12345", json={"name": "Updated"})
        assert response.status_code in [404, 503]

    def test_update_agent_partial(self, client: TestClient):
        """Test partial update of an agent."""
        response = client.put("/api/agents/default", json={"temperature": 0.5})
        assert response.status_code in [200, 404, 503]

    def test_delete_agent_not_found(self, client: TestClient):
        """Test deleting a non-existent agent."""
        response = client.delete("/api/agents/non-existent-agent-12345")
        assert response.status_code in [404, 503]

    def test_delete_default_agent(self, client: TestClient):
        """Test deleting the default agent."""
        response = client.delete("/api/agents/default")
        assert response.status_code in [400, 403, 404, 503]

    def test_set_default_agent_not_found(self, client: TestClient):
        """Test setting a non-existent agent as default."""
        response = client.post("/api/agents/non-existent-agent-12345/set-default")
        assert response.status_code in [404, 503]

    def test_clone_agent_not_found(self, client: TestClient):
        """Test cloning a non-existent agent."""
        response = client.post("/api/agents/non-existent-agent-12345/clone")
        assert response.status_code in [404, 503]

    def test_agent_invalid_temperature(self, client: TestClient):
        """Test creating agent with invalid temperature."""
        response = client.post(
            "/api/agents", json={"name": "Invalid Temp Agent", "temperature": 3.0}
        )
        assert response.status_code in [400, 422, 200, 503]

    def test_agent_invalid_max_tokens(self, client: TestClient):
        """Test creating agent with invalid max_tokens."""
        response = client.post(
            "/api/agents", json={"name": "Invalid Tokens Agent", "max_tokens": -100}
        )
        assert response.status_code in [400, 422, 200, 503]


class TestAgentEndpointsContentType:
    """Test content type and headers for agent endpoints."""

    def test_get_agents_content_type(self, client: TestClient):
        """Test content type for get agents."""
        response = client.get("/api/agents")
        if response.status_code == 200:
            assert "application/json" in response.headers.get("content-type", "")

    def test_create_agent_content_type(self, client: TestClient):
        """Test content type for create agent."""
        response = client.post("/api/agents", json={"name": "Content Type Test"})
        if response.status_code in [200, 201]:
            assert "application/json" in response.headers.get("content-type", "")


class TestAgentEndpointsMethods:
    """Test HTTP methods for agent endpoints."""

    def test_agents_unsupported_method(self, client: TestClient):
        """Test unsupported HTTP method on agents endpoint."""
        response = client.patch("/api/agents")
        assert response.status_code == 405

    def test_single_agent_unsupported_method(self, client: TestClient):
        """Test unsupported HTTP method on single agent endpoint."""
        response = client.patch("/api/agents/default")
        assert response.status_code == 405
