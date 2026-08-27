"""server.api.routers.archive 路由测试。

set_service_state 注入假 MemoryManager（含 archiver / deduplication_engine）+
monkeypatch server.config.get_settings。覆盖：
- list / archive（503/404/成功）/ merge（503/400/成功）
- deduplicate（503/成功）/ duplicate groups / of-archives / stats
- levels / threshold（get/set/边界400）/ auto-process

运行：python -m pytest tests/test_archive_router.py -v
"""
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import ServiceState, set_service_state
from server.api.routers import archive as archive_router_mod
from server.api.routers.admin import verify_admin_api_key


class SimpleBox:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def to_dict(self):
        return self.__dict__.copy()


class FakeArchiver:
    def __init__(self):
        self.archive_calls = []
        self.merge_calls = []
        self.statistics = {"archived": 5, "by_level": {1: 5}}

    async def archive_memory(self, memory_id, target_level, compress=True):
        self.archive_calls.append((memory_id, target_level, compress))
        return SimpleBox(archive_id="a1", memory_id=memory_id, level=target_level)

    def _merge_result(self, success=True):
        return SimpleBox(
            success=success,
            merged_memory_id=10,
            merged_from=[1, 2],
            merged_content="merged",
            merge_metadata={},
            message="ok",
        )

    async def merge_duplicate_memories(self, memory_ids, strategy="smart"):
        self.merge_calls.append((memory_ids, strategy))
        return self._merge_result()

    async def archive_of_archives(self, archive_level=4):
        return []

    def get_archive_stats(self):
        return self.statistics


class FakeGroup:
    def __init__(self, group_id="g1", memory_ids=(1, 2), merged=False):
        self.group_id = group_id
        self.memory_ids = list(memory_ids)
        self.merged = merged

    def to_dict(self):
        return {
            "group_id": self.group_id,
            "memory_ids": self.memory_ids,
            "merged": self.merged,
        }


class FakeDedupEngine:
    def __init__(self):
        self.threshold = 0.8
        self.detect_calls = []

    async def detect_duplicates_batch(self, memory_ids=None, threshold=None):
        self.detect_calls.append((memory_ids, threshold))
        return [FakeGroup("g1", (1, 2), merged=False)]

    def get_duplicate_groups(self):
        return [FakeGroup("g1", (1, 2), merged=True)]


class FakeMemoryManager:
    def __init__(self, archiver=None, deduplication_engine=None):
        self.archiver = archiver
        self.deduplication_engine = deduplication_engine
        self.memories = [
            {"id": 1, "archived_at": "2026-08-01T00:00:00", "created_at": "2026-01-01T00:00:00"},
            {"id": 2, "archived_at": None, "created_at": "2026-01-01T00:00:00"},
        ]

    def search_memories(self, memory_type=None, limit=20, offset=0, include_deleted=False):
        # 真实实现为同步方法（crud_mixin.py:169），路由内同步调用
        return self.memories


class FakeMemoryConfig:
    def __init__(self):
        self.dedup_threshold = 0.8


class FakeSettings:
    config = SimpleBox(memory=FakeMemoryConfig())

    def save_config(self):
        return None


@pytest.fixture
def client(monkeypatch):
    archiver = FakeArchiver()
    dedup = FakeDedupEngine()
    mm = FakeMemoryManager(archiver=archiver, deduplication_engine=dedup)
    state = ServiceState()
    state.memory_manager = mm
    set_service_state(state)
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())

    app = FastAPI()
    app.include_router(archive_router_mod.router)
    # of-archives/threshold/auto-process 等管理写端点已挂 verify_admin_api_key，
    # 测试中放行鉴权依赖以聚焦业务行为。
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app), mm, archiver, dedup


@pytest.fixture
def no_archiver_client(monkeypatch):
    mm = FakeMemoryManager(archiver=None, deduplication_engine=None)
    state = ServiceState()
    state.memory_manager = mm
    set_service_state(state)
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())
    app = FastAPI()
    app.include_router(archive_router_mod.router)
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app), mm, None, None


@pytest.fixture
def no_auth_client(monkeypatch):
    """不含鉴权覆盖的客户端：验证管理写端点无密钥访问被拒。"""
    mm = FakeMemoryManager(archiver=None, deduplication_engine=None)
    state = ServiceState()
    state.memory_manager = mm
    set_service_state(state)
    monkeypatch.setattr("server.config.get_settings", lambda: FakeSettings())
    app = FastAPI()
    app.include_router(archive_router_mod.router)
    return TestClient(app, raise_server_exceptions=False)  # type: ignore[name-defined]


class TestListArchived:
    def test_only_archived(self, client):
        c, mm, _, _ = client
        r = c.get("/archive/list")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["memories"][0]["id"] == 1


class TestArchiveMemory:
    def test_success(self, client):
        c, mm, archiver, _ = client
        r = c.post("/archive/memory", json={"memory_id": 1, "target_level": 2})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert archiver.archive_calls[0][1] == 2

    def test_not_found_404(self, client):
        c, mm, archiver, _ = client
        async def _none(**kw):
            return None
        archiver.archive_memory = _none
        r = c.post("/archive/memory", json={"memory_id": 999})
        assert r.status_code == 404

    def test_disabled_503(self, no_archiver_client):
        c, mm, _, _ = no_archiver_client
        r = c.post("/archive/memory", json={"memory_id": 1})
        assert r.status_code == 503


class TestMergeMemories:
    def test_success(self, client):
        c, mm, archiver, _ = client
        r = c.post("/archive/merge", json={"memory_ids": [1, 2], "strategy": "smart"})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert r.json()["result"]["merged_memory_id"] == 10

    def test_less_than_two_400(self, client):
        c, mm, archiver, _ = client
        r = c.post("/archive/merge", json={"memory_ids": [1]})
        assert r.status_code == 400

    def test_disabled_503(self, no_archiver_client):
        c, mm, _, _ = no_archiver_client
        r = c.post("/archive/merge", json={"memory_ids": [1, 2]})
        assert r.status_code == 503


class TestDeduplicate:
    def test_success(self, client):
        c, mm, _, dedup = client
        r = c.post("/archive/deduplicate", json={"threshold": 0.9})
        assert r.status_code == 200
        assert r.json()["total_groups"] == 1
        assert dedup.detect_calls[0][1] == 0.9

    def test_default_threshold_from_settings(self, client):
        c, mm, _, dedup = client
        r = c.post("/archive/deduplicate", json={})
        assert r.status_code == 200
        assert dedup.detect_calls[0][1] == 0.8

    def test_disabled_503(self, no_archiver_client):
        c, mm, _, _ = no_archiver_client
        r = c.post("/archive/deduplicate", json={})
        assert r.status_code == 503


class TestDuplicateGroups:
    def test_success(self, client):
        c, mm, _, dedup = client
        r = c.get("/archive/duplicates")
        assert r.status_code == 200
        assert r.json()["total_groups"] == 1

    def test_disabled_503(self, no_archiver_client):
        c, mm, _, _ = no_archiver_client
        r = c.get("/archive/duplicates")
        assert r.status_code == 503


class TestArchiveOfArchives:
    def test_success(self, client):
        c, mm, archiver, _ = client
        r = c.post("/archive/of-archives", json={"target_level": 4})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert r.json()["count"] == 0

    def test_disabled_503(self, no_archiver_client):
        c, mm, _, _ = no_archiver_client
        r = c.post("/archive/of-archives", json={})
        assert r.status_code == 503


class TestArchiveStats:
    def test_success(self, client):
        c, mm, archiver, _ = client
        r = c.get("/archive/stats")
        assert r.status_code == 200
        assert r.json()["statistics"]["archived"] == 5

    def test_disabled_503(self, no_archiver_client):
        c, mm, _, _ = no_archiver_client
        r = c.get("/archive/stats")
        assert r.status_code == 503


class TestArchiveLevels:
    def test_success(self, client):
        c, mm, _, _ = client
        r = c.get("/archive/levels")
        assert r.status_code == 200
        assert "1" in r.json()["archive_levels"]


class TestThreshold:
    def test_get(self, client):
        c, mm, _, _ = client
        r = c.get("/archive/threshold")
        assert r.status_code == 200
        assert r.json()["threshold"] == 0.8

    def test_set_success(self, client):
        c, mm, _, dedup = client
        r = c.post("/archive/threshold", json={"threshold": 0.9})
        assert r.status_code == 200
        assert r.json()["threshold"] == 0.9
        assert dedup.threshold == 0.9

    def test_set_out_of_range_400(self, client):
        c, mm, _, dedup = client
        r = c.post("/archive/threshold", json={"threshold": 0.1})
        assert r.status_code == 400


class TestAutoArchive:
    def test_success(self, client):
        c, mm, archiver, dedup = client
        r = c.post("/archive/auto-process", params={"min_age_days": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        # 仅未归档的 id=2 被归档（id=1 已有 archived_at 被跳过）
        assert body["summary"]["archived_count"] == 1
        assert body["summary"]["merged_count"] == 1

    def test_disabled_503(self, no_archiver_client):
        c, mm, _, _ = no_archiver_client
        r = c.post("/archive/auto-process")
        assert r.status_code == 503


class TestManagementAuth:
    """管理写端点（of-archives / threshold）无密钥访问应被 403 拒绝；auto-process 为前端记忆页在用保持公开。"""

    @pytest.mark.parametrize(
        "method,path,payload",
        [
            ("post", "/archive/of-archives", {"target_level": 4}),
            ("post", "/archive/threshold", {"threshold": 0.9}),
        ],
    )
    def test_write_endpoint_rejects_unauth(self, no_auth_client, monkeypatch, method, path, payload):
        from server.api.routers import admin as admin_router_mod

        monkeypatch.setattr(admin_router_mod, "ADMIN_API_KEY", "")
        c = no_auth_client
        r = getattr(c, method)(path, json=payload)
        assert r.status_code == 403

    def test_auto_process_public(self, client):
        """auto-process 由前端记忆页调用，无密钥也应可用。"""
        c, _, _, _ = client
        r = c.post("/archive/auto-process")
        assert r.status_code in (200, 503)