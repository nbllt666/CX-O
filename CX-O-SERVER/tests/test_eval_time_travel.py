"""POST /api/memories/eval/time-travel 时间旅行评测端点 + shift_memory_time 单元测试。

覆盖：回拨生效、累积回拨、衰减统计变化（衰减管线被触发）、tags/memory_ids
过滤无部分写入、400 校验（shift_days 越界/负数、agent_id 为空）、404（无记忆）、
403（admin key 未配置/不匹配，按 admin.py:80-87 实际逻辑：未配置即 403）。

fixture 沿用 tests/test_memory_manager.py 模式：tmp_path 独立库 + monkeypatch
禁后台线程 + 重置单例；路由层沿用 tests/test_memory_router.py 模式：
FastAPI + dependency_overrides 注入真实 MemoryManager。

运行：python -m pytest tests/test_eval_time_travel.py -v
"""
import sqlite3
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import memory as memory_router_mod
from server.core.memory.manager import MemoryManager
from server.dependencies import ServiceState, get_memory_manager, set_service_state

ADMIN_KEY = "test-admin-key-123"


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """每个用例独立的临时数据库 MemoryManager（禁用后台线程）。"""
    monkeypatch.setattr(MemoryManager, "_start_cleanup_task", lambda self: None)

    def _noop_init(self):
        self.archiver = None
        self.deduplication_engine = None
        self.vectorization_queue = None

    monkeypatch.setattr(MemoryManager, "_init_advanced_components", _noop_init)

    MemoryManager._instance = None
    MemoryManager._instances.clear()
    m = MemoryManager(db_path=str(tmp_path / "memories.db"))
    yield m
    m.shutdown()
    MemoryManager._instance = None
    MemoryManager._instances.clear()


@pytest.fixture
def client(mgr, monkeypatch):
    """TestClient：ServiceState 注入真实 mgr（端点函数体内直接调用
    get_memory_manager，不走 DI override，须 set_service_state），
    并配置 admin key。"""
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    state = ServiceState()
    state.memory_manager = mgr
    set_service_state(state)
    app = FastAPI()
    app.include_router(memory_router_mod.router)
    app.dependency_overrides[get_memory_manager] = lambda: mgr
    yield TestClient(app, raise_server_exceptions=False)
    set_service_state(ServiceState())


def _seed(mgr, content, agent_id="default", tags=None):
    """写入一条记忆并补齐 updated_at（write_memory 不写该列，模拟已有更新）。"""
    mid = mgr.write_memory(content=content, agent_id=agent_id, tags=tags or [])
    table = mgr._get_table_name(agent_id)
    conn = sqlite3.connect(str(mgr.db_path))
    try:
        conn.execute(f"UPDATE {table} SET updated_at = created_at WHERE id = ?", (mid,))
        conn.commit()
    finally:
        conn.close()
    return mid


def _fetch_ts(mgr, mid, agent_id="default"):
    """直连临时库读取原始时间戳（返回 datetime 元组）。"""
    table = mgr._get_table_name(agent_id)
    conn = sqlite3.connect(str(mgr.db_path))
    try:
        row = conn.execute(
            f"SELECT created_at, updated_at FROM {table} WHERE id = ?", (mid,)
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return tuple(datetime.fromisoformat(v.replace(" ", "T", 1)) for v in row)


def _days_between(new_dt, old_dt):
    return (new_dt - old_dt).total_seconds() / 86400.0


class TestShiftEffective:
    def test_shift_back_365_days(self, client, mgr):
        """种 2 条记忆 → shift 365 天 → created_at/updated_at 均提前 365 天。"""
        id1 = _seed(mgr, "记忆一")
        id2 = _seed(mgr, "记忆二")
        before1 = _fetch_ts(mgr, id1)
        before2 = _fetch_ts(mgr, id2)

        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 365},
            headers={"X-API-Key": ADMIN_KEY},
        )

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["shifted_count"] == 2

        after1 = _fetch_ts(mgr, id1)
        after2 = _fetch_ts(mgr, id2)
        for before, after in ((before1, after1), (before2, after2)):
            assert abs(_days_between(after[0], before[0]) + 365) < 0.001
            assert abs(_days_between(after[1], before[1]) + 365) < 0.001


class TestCumulativeShift:
    def test_three_times_365_days(self, client, mgr):
        """连续 shift 365 天 ×3 → 时间戳叠加 ≈1095 天。"""
        mid = _seed(mgr, "长期记忆")
        before = _fetch_ts(mgr, mid)

        for _ in range(3):
            r = client.post(
                "/memories/eval/time-travel",
                json={"agent_id": "default", "shift_days": 365},
                headers={"X-API-Key": ADMIN_KEY},
            )
            assert r.status_code == 200
            assert r.json()["shifted_count"] == 1

        after = _fetch_ts(mgr, mid)
        assert abs(_days_between(after[0], before[0]) + 1095) < 0.002
        assert abs(_days_between(after[1], before[1]) + 1095) < 0.002


class TestDecayStatsChanged:
    def test_avg_time_score_decreases_after_shift(self, client, mgr):
        """回拨后衰减统计变化（证明衰减管线按回拨后 created_at 生效）。"""
        _seed(mgr, "衰减观察一")
        _seed(mgr, "衰减观察二")

        stats_before = mgr.sync_decay_values()
        before_score = stats_before["avg_time_score"]

        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 365},
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 200

        stats_after = mgr.sync_decay_values()
        after_score = stats_after["avg_time_score"]

        # sync_decay_values 为实时计算模式：时间分由 created_at 即时推导
        assert stats_after["mode"] == "realtime"
        assert stats_before["total"] == 2
        assert stats_after["total"] == 2
        assert after_score < before_score


class TestFilterNoPartialWrite:
    def test_tags_filter_leaves_unmatched_untouched(self, client, mgr):
        """tags 过滤：匹配的 2 条回拨，未匹配记忆时间戳不变。"""
        id_a = _seed(mgr, "带衰减标签A", tags=["decay"])
        id_b = _seed(mgr, "带衰减标签B", tags=["decay"])
        id_c = _seed(mgr, "无关标签", tags=["other"])
        before_a = _fetch_ts(mgr, id_a)
        before_b = _fetch_ts(mgr, id_b)
        before_c = _fetch_ts(mgr, id_c)

        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 100, "tags": ["decay"]},
            headers={"X-API-Key": ADMIN_KEY},
        )

        assert r.status_code == 200
        assert r.json()["shifted_count"] == 2

        after_a = _fetch_ts(mgr, id_a)
        after_b = _fetch_ts(mgr, id_b)
        after_c = _fetch_ts(mgr, id_c)
        assert abs(_days_between(after_a[0], before_a[0]) + 100) < 0.001
        assert abs(_days_between(after_b[1], before_b[1]) + 100) < 0.001
        # 未匹配记忆时间戳原样不变
        assert after_c == before_c

    def test_memory_ids_filter(self, client, mgr):
        """memory_ids 过滤：仅指定 id 回拨，其余不变。"""
        id_a = _seed(mgr, "选中记忆")
        id_b = _seed(mgr, "未选中记忆")
        before_b = _fetch_ts(mgr, id_b)

        r = client.post(
            "/memories/eval/time-travel",
            json={
                "agent_id": "default",
                "shift_days": 50,
                "memory_ids": [id_a],
            },
            headers={"X-API-Key": ADMIN_KEY},
        )

        assert r.status_code == 200
        assert r.json()["shifted_count"] == 1
        # id_b 未被触碰
        assert _fetch_ts(mgr, id_b) == before_b

    def test_deleted_memories_skipped(self, client, mgr):
        """已软删除的记忆不参与回拨。"""
        id_keep = _seed(mgr, "存活记忆")
        id_gone = _seed(mgr, "已删记忆")
        mgr.delete_memory(id_gone, soft_delete=True, agent_id="default")
        before_keep = _fetch_ts(mgr, id_keep)

        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 30},
            headers={"X-API-Key": ADMIN_KEY},
        )

        assert r.status_code == 200
        assert r.json()["shifted_count"] == 1
        assert abs(_days_between(_fetch_ts(mgr, id_keep)[0], before_keep[0]) + 30) < 0.001


class TestValidation400:
    @pytest.mark.parametrize("bad_days", [0, 3651, -5])
    def test_invalid_shift_days(self, client, mgr, bad_days):
        _seed(mgr, "校验用记忆")
        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": bad_days},
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 400

    def test_empty_agent_id_maps_valueerror_to_400(self, client, mgr):
        _seed(mgr, "agent校验用记忆")
        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "", "shift_days": 10},
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 400

    def test_missing_agent_id_422(self, client):
        """agent_id 必填：缺失时 pydantic 返回 422。"""
        r = client.post(
            "/memories/eval/time-travel",
            json={"shift_days": 10},
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 422


class TestNotFound404:
    def test_agent_without_memories(self, client, mgr):
        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "eval_empty_agent", "shift_days": 30},
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 404

    def test_tags_match_nothing(self, client, mgr):
        """tags 无匹配（shifted_count==0）→ 404，且记忆不被改动。"""
        mid = _seed(mgr, "幽灵标签记忆")
        before = _fetch_ts(mgr, mid)
        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 30, "tags": ["ghost"]},
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 404
        assert _fetch_ts(mgr, mid) == before


class TestAdminKey403:
    def test_403_when_admin_key_not_configured(self, mgr, monkeypatch):
        """admin.py 实际逻辑：ADMIN_API_KEY 未配置时 verify_admin_api_key 直接 403。"""
        monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        app = FastAPI()
        app.include_router(memory_router_mod.router)
        app.dependency_overrides[get_memory_manager] = lambda: mgr
        c = TestClient(app, raise_server_exceptions=False)

        r = c.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 30},
        )
        assert r.status_code == 403

    def test_403_without_key_header(self, client, mgr):
        """配置了 admin key 但请求未携带 → 403。"""
        _seed(mgr, "鉴权用记忆")
        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 30},
        )
        assert r.status_code == 403

    def test_403_with_wrong_key(self, client, mgr):
        _seed(mgr, "鉴权用记忆")
        r = client.post(
            "/memories/eval/time-travel",
            json={"agent_id": "default", "shift_days": 30},
            headers={"X-API-Key": "wrong-key"},
        )
        assert r.status_code == 403
