"""R9 分页参数钳制单测。

覆盖 5 处路由端点的 limit/offset 钳制行为（对齐 tuner.py:252 惯例
limit = max(1, min(int(limit), 200))、offset = max(0, int(offset))）：
- memory.list_memories（Query 参数钳制，含 permanent 分支 get_permanent_memories 直传点）
- MemorySearchRequest（Pydantic 模型字段边界约束 ge/le）
- admin.admin_audit
- autonomy.list_audit
- dream.list_candidates
- decision.get_rejected_content

断言口径：limit=10**9 时下游收到 200（上限行为）；offset=-5 不抛错且钳为 0。

运行：python -m pytest tests/test_pagination_clamp.py -v
"""
import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from server.api.routers import admin as admin_router
from server.api.routers import autonomy as autonomy_router
from server.api.routers import decision as decision_router
from server.api.routers import dream as dream_router
from server.api.routers import memory as memory_router
from server.api.routers.memory import MemorySearchRequest


class RecordingMemoryManager:
    """记录 search_memories / get_permanent_memories 收到的分页参数。"""

    def __init__(self):
        self.search_calls = []
        self.permanent_calls = []

    def search_memories(self, **kwargs):
        self.search_calls.append(kwargs)
        return []

    def get_permanent_memories(self, **kwargs):
        self.permanent_calls.append(kwargs)
        return []


def _make_request(services) -> Request:
    """构造带 app.state.services 的最小 starlette Request（decision 端点用）。"""
    app = SimpleNamespace(state=SimpleNamespace(services=services))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/decision/rejected/s1",
        "headers": [],
        "query_string": b"",
        "app": app,
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# memory.py
# ---------------------------------------------------------------------------

def test_list_memories_clamps_limit_and_offset(monkeypatch):
    """limit=10**9/offset=-5 → 下游 search_memories 收到 (200, 0)，不抛错。"""
    mgr = RecordingMemoryManager()
    monkeypatch.setattr("server.dependencies.get_memory_manager", lambda: mgr)

    result = asyncio.run(
        memory_router.list_memories(
            workspace_id="default",
            type=None,
            memory_type=None,
            limit=10**9,
            offset=-5,
            agent_id="default",
        )
    )
    assert result["status"] == "success"
    assert mgr.search_calls == [
        {
            "memory_type": None,
            "limit": 200,
            "offset": 0,
            "workspace_id": "default",
            "agent_id": "default",
        }
    ]


def test_list_memories_permanent_branch_clamps(monkeypatch):
    """permanent 分支：get_permanent_memories 直传点同样收到钳制后的参数。"""
    mgr = RecordingMemoryManager()
    monkeypatch.setattr("server.dependencies.get_memory_manager", lambda: mgr)

    asyncio.run(
        memory_router.list_memories(
            workspace_id="default", type="permanent", memory_type=None,
            limit=10**9, offset=-5, agent_id="default",
        )
    )
    assert mgr.permanent_calls == [{"limit": 200, "offset": 0}]


def test_memory_search_request_model_bounds():
    """MemorySearchRequest 模型字段：le=200/ge=0 边界约束（上限行为）。"""
    with pytest.raises(ValidationError):
        MemorySearchRequest(limit=10**9)
    with pytest.raises(ValidationError):
        MemorySearchRequest(offset=-5)
    req = MemorySearchRequest()
    assert req.limit == 10
    assert req.offset == 0
    edge = MemorySearchRequest(limit=200, offset=0)
    assert edge.limit == 200


# ---------------------------------------------------------------------------
# admin.py
# ---------------------------------------------------------------------------

def test_admin_audit_clamps_limit_and_offset(monkeypatch):
    """admin_audit：_audit_read 收到钳制后的 (200, 0)。"""
    calls = []
    monkeypatch.setattr(admin_router, "_admin_guard", lambda request, level: None)

    import server.core.admin.cluster_bridge as bridge

    def fake_audit_read(limit, offset):
        calls.append((limit, offset))
        return []

    monkeypatch.setattr(bridge, "_audit_read", fake_audit_read)

    result = asyncio.run(
        admin_router.admin_audit(None, limit=10**9, offset=-5)
    )
    assert result["status"] == "success"
    assert calls == [(200, 0)]


# ---------------------------------------------------------------------------
# autonomy.py
# ---------------------------------------------------------------------------

def test_autonomy_list_audit_clamps_limit_and_offset(monkeypatch):
    """list_audit：AuditStore.list 收到钳制后的 (200, 0)。"""
    calls = []

    class FakeStore:
        def list(self, limit, offset):
            calls.append((limit, offset))
            return {"items": [], "total": 0}

    monkeypatch.setattr(autonomy_router, "_audit_store", FakeStore())

    result = autonomy_router.list_audit(limit=10**9, offset=-5)
    assert result == {"items": [], "total": 0}
    assert calls == [(200, 0)]


# ---------------------------------------------------------------------------
# dream.py
# ---------------------------------------------------------------------------

def test_dream_list_candidates_clamps_limit_and_offset(monkeypatch):
    """list_candidates：buffer.list 收到钳制后的 (200, 0)，offset=-5 不抛错。"""
    calls = []

    class FakeBuffer:
        def list(self, **kwargs):
            calls.append(kwargs)
            return []

        def count(self, **kwargs):
            return 0

    fake_engine = SimpleNamespace(
        config=SimpleNamespace(enabled=True), buffer=FakeBuffer()
    )
    monkeypatch.setattr(dream_router, "_engine", fake_engine)

    result = dream_router.list_candidates(
        agent_id="default", state=None, limit=10**9, offset=-5
    )
    assert result == {"items": [], "total": 0}
    assert calls == [
        {"agent_id": "default", "decision": None, "limit": 200, "offset": 0}
    ]


# ---------------------------------------------------------------------------
# decision.py
# ---------------------------------------------------------------------------

def test_decision_get_rejected_content_clamps_limit(monkeypatch):
    """get_rejected_content：mm.get_rejected_content 收到钳制后的 limit=200。"""
    calls = []

    class FakeMM:
        def get_rejected_content(self, session_id=None, limit=None):
            calls.append((session_id, limit))
            return []

    request = _make_request(SimpleNamespace(memory_manager=FakeMM()))

    result = asyncio.run(
        decision_router.get_rejected_content("s1", request, limit=10**9)
    )
    assert result["count"] == 0
    assert calls == [("s1", 200)]
