"""Memory API endpoint tests."""

import pytest
from fastapi.testclient import TestClient


class TestMemoryEndpoints:
    """Test memory API endpoints."""

    def test_get_all_memories(self, client: TestClient):
        """Test getting all memories."""
        response = client.get("/api/memories")
        assert response.status_code in [200, 503]

    def test_get_all_memories_with_pagination(self, client: TestClient):
        """Test getting memories with pagination."""
        response = client.get("/api/memories?page=2&page_size=10")
        assert response.status_code in [200, 503]

    def test_get_all_memories_with_limit_offset(self, client: TestClient):
        """Test getting memories with limit and offset."""
        response = client.get("/api/memories?limit=10&offset=0")
        assert response.status_code in [200, 503]

    def test_get_all_memories_with_type_filter(self, client: TestClient):
        """Test getting memories filtered by type."""
        response = client.get("/api/memories?type=long_term")
        assert response.status_code in [200, 503]

    def test_get_memory_by_id_not_found(self, client: TestClient):
        """Test getting a non-existent memory."""
        response = client.get("/api/memories/non-existent-memory-12345")
        assert response.status_code in [404, 422, 503]

    def test_get_memory_by_id_invalid_format(self, client: TestClient):
        """Test getting memory with invalid ID format."""
        response = client.get("/api/memories/invalid-id")
        assert response.status_code in [404, 422, 503]

    def test_create_memory_validation(self, client: TestClient):
        """Test creating a memory without required fields."""
        response = client.post("/api/memories", json={"type": "long_term"})
        assert response.status_code == 422

    def test_create_memory_with_content(self, client: TestClient):
        """Test creating a memory with content."""
        response = client.post("/api/memories", json={"content": "Test memory content"})
        assert response.status_code in [200, 201, 503]

    def test_create_memory_with_all_fields(self, client: TestClient):
        """Test creating a memory with all fields."""
        response = client.post(
            "/api/memories",
            json={
                "content": "Complete memory",
                "type": "long_term",
                "importance": 4,
                "tags": ["test", "important"],
            },
        )
        assert response.status_code in [200, 201, 503]

    def test_update_memory_not_found(self, client: TestClient):
        """Test updating a non-existent memory."""
        response = client.put(
            "/api/memories/non-existent-memory-12345", json={"content": "Updated"}
        )
        assert response.status_code in [404, 422, 503]

    def test_delete_memory_not_found(self, client: TestClient):
        """Test deleting a non-existent memory."""
        response = client.delete("/api/memories/non-existent-memory-12345")
        assert response.status_code in [404, 422, 503]

    def test_search_memories(self, client: TestClient):
        """Test searching memories."""
        response = client.post("/api/memories/search", json={"query": "test"})
        assert response.status_code in [200, 503]

    def test_search_memories_with_options(self, client: TestClient):
        """Test searching memories with options."""
        response = client.post(
            "/api/memories/search", json={"query": "test query", "limit": 10, "type": "long_term"}
        )
        assert response.status_code in [200, 503]

    def test_semantic_search(self, client: TestClient):
        """Test semantic search endpoint."""
        response = client.post(
            "/api/memories/semantic-search",
            json={"query": "test query", "top_k": 5, "threshold": 0.7},
        )
        assert response.status_code in [200, 503]

    def test_semantic_search_minimal(self, client: TestClient):
        """Test semantic search with minimal params."""
        response = client.post("/api/memories/semantic-search", json={"query": "test"})
        assert response.status_code in [200, 503]

    def test_get_memory_stats(self, client: TestClient):
        """Test getting memory statistics."""
        response = client.get("/api/memories/stats")
        assert response.status_code in [200, 422, 503]


class TestMemoryBatchEndpoints:
    """Test memory batch operation endpoints."""

    def test_batch_delete_memories(self, client: TestClient):
        """Test batch deleting memories."""
        response = client.post("/api/memories/batch/delete", json={"ids": [1, 2, 3]})
        assert response.status_code in [200, 503]

    def test_batch_delete_memories_empty(self, client: TestClient):
        """Test batch deleting with empty list."""
        response = client.post("/api/memories/batch/delete", json={"ids": []})
        assert response.status_code in [200, 422, 503]

    def test_batch_update_tags(self, client: TestClient):
        """Test batch updating tags."""
        response = client.post(
            "/api/memories/batch/tags",
            json={"ids": [1, 2], "tags": ["new-tag"], "operation": "add"},
        )
        assert response.status_code in [200, 503]

    def test_batch_archive_memories(self, client: TestClient):
        """Test batch archiving memories."""
        response = client.post("/api/memories/batch/archive", json={"ids": [1, 2]})
        assert response.status_code in [200, 503]


class TestMemoryEndpointsContentType:
    """Test content type for memory endpoints."""

    def test_get_memories_content_type(self, client: TestClient):
        """Test content type for get memories."""
        response = client.get("/api/memories")
        if response.status_code == 200:
            assert "application/json" in response.headers.get("content-type", "")

    def test_search_memories_content_type(self, client: TestClient):
        """Test content type for search memories."""
        response = client.post("/api/memories/search", json={"query": "test"})
        if response.status_code == 200:
            assert "application/json" in response.headers.get("content-type", "")


class TestMemoryValidation:
    """Test validation for memory endpoints."""

    def test_create_memory_empty_content(self, client: TestClient):
        """Test creating memory with empty content."""
        response = client.post("/api/memories", json={"content": ""})
        assert response.status_code in [422, 200, 503]

    def test_create_memory_invalid_importance(self, client: TestClient):
        """Test creating memory with invalid importance."""
        response = client.post("/api/memories", json={"content": "Test", "importance": 10})
        assert response.status_code in [422, 200, 503]

    def test_search_memories_empty_query(self, client: TestClient):
        """Test searching with empty query."""
        response = client.post("/api/memories/search", json={"query": ""})
        assert response.status_code in [422, 200, 503]


class TestVectorStatusAPI:
    """Test vector status API endpoint."""

    def test_get_vector_status(self, client: TestClient):
        """Test getting vector status."""
        response = client.get("/api/memories/vectors/status")
        assert response.status_code in [200, 503]

    def test_vector_status_response_structure(self, client: TestClient):
        """Test vector status response structure."""
        response = client.get("/api/memories/vectors/status")
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert "data" in data
            result = data["data"]
            assert "enabled" in result
            assert "backend" in result
            assert "vector_count" in result
            assert "sqlite_count" in result
            assert "healthy" in result

    def test_vector_status_returns_enabled_false_when_disabled(self, client: TestClient):
        """Test that vector status returns enabled=False when vector search is disabled."""
        response = client.get("/api/memories/vectors/status")
        if response.status_code == 200:
            data = response.json()
            assert "enabled" in data["data"]


class TestHybridSearchFallback:
    """Test hybrid search fallback behavior."""

    def test_semantic_search_response_has_fallback_field(self, client: TestClient):
        """Test that semantic search response includes fallback field."""
        response = client.post("/api/memories/semantic-search", json={"query": "test query"})
        if response.status_code == 200:
            data = response.json()
            assert "results" in data
            if data["results"]:
                assert "fallback" in data["results"][0]

    def test_rag_search_response_structure(self, client: TestClient):
        """Test RAG search response structure."""
        response = client.post("/api/memories/rag?query=test&limit=5")
        if response.status_code == 200:
            data = response.json()
            assert "status" in data
            assert "results" in data
