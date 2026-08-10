"""server.api.routers.backup 路由测试。

monkeypatch server.core.backup.get_backup_manager 为假 manager + dependency_overrides
覆盖 verify_admin_api_key（受保护端点放行）。覆盖：
- list / create（full/incremental/differential）/ stats / get（404）
- restore（404）/ delete（404/500）/ import（成功/损坏 400）/ export（404/成功）
- 异常映射：manager 抛异常→500

运行：python -m pytest tests/test_backup_router.py -v
"""
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.core import backup as backup_core
from server.api.routers import backup as backup_router_mod
from server.api.routers.admin import verify_admin_api_key


class FakeManager:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.backups = {
            "b1": {
                "id": "b1", "backup_type": "full", "status": "completed",
                "created_at": "2026-08-09T00:00:00", "completed_at": None,
                "description": "full backup", "size_bytes": 100,
                "compressed_size": 50, "file_count": 3,
                "path": str(tmp_path / "b1.zip"),
            },
            "b2": {
                "id": "b2", "backup_type": "incremental", "status": "completed",
                "created_at": "2026-08-09T01:00:00", "completed_at": None,
                "description": None, "size_bytes": 20,
                "compressed_size": 10, "file_count": 1,
                "path": str(tmp_path / "b2.zip"),
            },
        }
        self.import_result = None

    def list_backups(self):
        return list(self.backups.values())

    def get_status(self):
        return {"total_backups": len(self.backups)}

    def create_backup(self, backup_type, description=None):
        b = {
            "id": "b3", "backup_type": backup_type.value, "status": "completed",
            "created_at": "2026-08-09T02:00:00", "completed_at": None,
            "description": description, "size_bytes": 10,
            "compressed_size": 5, "file_count": 1, "path": "",
        }
        self.backups["b3"] = b
        return b

    def get_backup(self, backup_id):
        return self.backups.get(backup_id)

    def restore_backup(self, backup_id):
        return {"status": "success", "restored_files": 2, "failed_files": 0, "error_message": None}

    def delete_backup(self, backup_id):
        self.backups.pop(backup_id, None)
        return True

    def import_backup(self, path):
        if self.import_result is False:
            return None
        return {
            "id": "imp1", "backup_type": "full", "status": "completed",
            "created_at": "2026-08-09T03:00:00", "completed_at": None,
            "description": "imported", "size_bytes": 1,
            "compressed_size": 1, "file_count": 1, "path": "",
        }


@pytest.fixture
def client(monkeypatch, tmp_path):
    manager = FakeManager(tmp_path)
    # get_backup_manager 在 router 模块顶层绑定，patch 该模块引用
    monkeypatch.setattr(backup_router_mod, "get_backup_manager", lambda: manager)

    app = FastAPI()
    app.include_router(backup_router_mod.router)
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app, raise_server_exceptions=False), manager


class TestListBackups:
    def test_success(self, client):
        c, mgr = client
        r = c.get("/backups")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        # 响应字段映射
        assert body[0]["total_size"] == mgr.backups["b1"]["size_bytes"]


class TestCreateBackup:
    def test_full(self, client):
        c, mgr = client
        r = c.post("/backups", json={"backup_type": "full", "description": "d"})
        assert r.status_code == 200
        assert r.json()["backup_type"] == "full"

    def test_incremental(self, client):
        c, mgr = client
        r = c.post("/backups", json={"backup_type": "incremental"})
        assert r.status_code == 200
        assert r.json()["backup_type"] == "incremental"

    def test_differential(self, client):
        c, mgr = client
        r = c.post("/backups", json={"backup_type": "differential"})
        assert r.status_code == 200
        assert r.json()["backup_type"] == "differential"

    def test_requires_admin(self, client):
        c, mgr = client
        c.app.dependency_overrides[verify_admin_api_key] = lambda: (_ for _ in ()).throw(Exception("unauthorized"))
        r = c.post("/backups", json={"backup_type": "full"})
        assert r.status_code == 500


class TestBackupStats:
    def test_success(self, client):
        c, mgr = client
        r = c.get("/backups/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["total_backups"] == 2
        assert body["full_backups"] == 1
        assert body["incremental_backups"] == 1
        assert body["total_size"] == 120
        assert body["oldest_backup"] == "2026-08-09T00:00:00"
        assert body["latest_backup"] == "2026-08-09T01:00:00"


class TestGetBackup:
    def test_success(self, client):
        c, mgr = client
        r = c.get("/backups/b1")
        assert r.status_code == 200
        assert r.json()["id"] == "b1"

    def test_not_found_404(self, client):
        c, mgr = client
        r = c.get("/backups/nope")
        assert r.status_code == 404


class TestRestoreBackup:
    def test_success(self, client):
        c, mgr = client
        r = c.post("/backups/b1/restore")
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["restored_files"] == 2

    def test_not_found_404(self, client):
        c, mgr = client
        r = c.post("/backups/nope/restore")
        assert r.status_code == 404


class TestDeleteBackup:
    def test_success(self, client):
        c, mgr = client
        r = c.delete("/backups/b1")
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert "b1" not in mgr.backups

    def test_not_found_404(self, client):
        c, mgr = client
        r = c.delete("/backups/nope")
        assert r.status_code == 404

    def test_failure_500(self, client):
        c, mgr = client
        mgr.delete_backup = lambda bid: False
        r = c.delete("/backups/b1")
        assert r.status_code == 500


class TestImportBackup:
    def test_success(self, client):
        c, mgr = client
        mgr.import_result = True
        r = c.post("/backups/import", files={"file": ("b.zip", b"\x00", "application/zip")})
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_corrupt_400(self, client):
        c, mgr = client
        mgr.import_result = False
        r = c.post("/backups/import", files={"file": ("b.zip", b"\x00", "application/zip")})
        assert r.status_code == 400


class TestExportBackup:
    def test_success(self, client):
        c, mgr = client
        (mgr.tmp / "b1.zip").write_bytes(b"PK\x03\x04")
        r = c.get("/backups/b1/export")
        assert r.status_code == 200
        assert r.content == b"PK\x03\x04"

    def test_not_found_404(self, client):
        c, mgr = client
        r = c.get("/backups/nope/export")
        assert r.status_code == 404

    def test_file_missing_404(self, client):
        c, mgr = client
        r = c.get("/backups/b1/export")
        assert r.status_code == 404


class TestErrorMapping:
    def test_manager_exception_500(self, client):
        c, mgr = client
        mgr.list_backups = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        r = c.get("/backups")
        assert r.status_code == 500
        assert "boom" in r.json()["detail"]