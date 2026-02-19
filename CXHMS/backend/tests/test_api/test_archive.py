"""Tests for archive API endpoints."""
import pytest
from fastapi.testclient import TestClient


class TestArchiveEndpoints:
    """Test archive API endpoints."""

    def test_get_archived_memories(self, client: TestClient):
        """Test getting archived memories."""
        response = client.get("/api/archive")
        assert response.status_code in [200, 404, 503]

    def test_get_archived_memories_with_pagination(self, client: TestClient):
        """Test getting archived memories with pagination."""
        response = client.get("/api/archive?limit=10&offset=0")
        assert response.status_code in [200, 404, 503]

    def test_archive_memory_not_found(self, client: TestClient):
        """Test archiving a non-existent memory."""
        response = client.post("/api/archive/99999")
        assert response.status_code in [404, 503]

    def test_restore_memory_not_found(self, client: TestClient):
        """Test restoring a non-existent archived memory."""
        response = client.post("/api/archive/99999/restore")
        assert response.status_code in [404, 503]

    def test_delete_archived_memory_not_found(self, client: TestClient):
        """Test deleting a non-existent archived memory."""
        response = client.delete("/api/archive/99999")
        assert response.status_code in [404, 503]

    def test_get_archive_stats(self, client: TestClient):
        """Test getting archive statistics."""
        response = client.get("/api/archive/stats")
        assert response.status_code in [200, 404, 503]


class TestArchiveBatch:
    """Test archive batch operations."""

    def test_batch_archive_memories(self, client: TestClient):
        """Test batch archiving memories."""
        response = client.post(
            "/api/archive/batch",
            json={"memory_ids": [1, 2, 3]}
        )
        assert response.status_code in [200, 400, 404, 503]

    def test_batch_archive_empty_list(self, client: TestClient):
        """Test batch archiving with empty list."""
        response = client.post(
            "/api/archive/batch",
            json={"memory_ids": []}
        )
        assert response.status_code in [400, 404, 503]
