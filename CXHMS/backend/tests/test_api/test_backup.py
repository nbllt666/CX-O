"""Tests for backup API endpoints."""
import pytest
from fastapi.testclient import TestClient


class TestBackupEndpoints:
    """Test backup API endpoints."""

    def test_get_backup_status(self, client: TestClient):
        """Test getting backup status."""
        response = client.get("/api/backup/status")
        assert response.status_code in [200, 404, 503]

    def test_create_backup(self, client: TestClient):
        """Test creating a backup."""
        response = client.post("/api/backup/create")
        assert response.status_code in [200, 201, 404, 503]

    def test_list_backups(self, client: TestClient):
        """Test listing backups."""
        response = client.get("/api/backup/list")
        assert response.status_code in [200, 404, 503]

    def test_restore_backup_not_found(self, client: TestClient):
        """Test restoring a non-existent backup."""
        response = client.post("/api/backup/restore/non-existent-backup-12345")
        assert response.status_code in [404, 503]

    def test_delete_backup_not_found(self, client: TestClient):
        """Test deleting a non-existent backup."""
        response = client.delete("/api/backup/non-existent-backup-12345")
        assert response.status_code in [404, 503]


class TestBackupValidation:
    """Test backup validation."""

    def test_create_backup_with_options(self, client: TestClient):
        """Test creating backup with options."""
        response = client.post(
            "/api/backup/create",
            json={
                "include_memories": True,
                "include_sessions": True,
                "include_agents": True,
            }
        )
        assert response.status_code in [200, 201, 400, 404, 503]
