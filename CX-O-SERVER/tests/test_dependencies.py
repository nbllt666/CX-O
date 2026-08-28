"""
server/dependencies.py 单元测试
依赖解析（_resolve_state）、各 getter 的 503 降级、FastAPI Depends 标记识别、
per-agent 图数据库/图存储注册表（双重检查锁）、cxfc/document getter
"""
import threading

import pytest
from fastapi import Depends, HTTPException

import server.dependencies as deps
from server.dependencies import (
    ServiceState,
)


@pytest.fixture(autouse=True)
def _cleanup():
    """每测试清理全局状态，避免跨测试污染。"""
    deps.set_service_state(None)
    deps._graph_databases.clear()
    deps._graph_stores.clear()
    yield
    deps.set_service_state(None)
    deps._graph_databases.clear()
    deps._graph_stores.clear()


def _make_state(**kwargs):
    s = ServiceState()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# --------------------------------------------------------------------------- #
# _is_depends_marker & _resolve_state
# --------------------------------------------------------------------------- #
class TestResolveState:
    def test_is_depends_marker(self):
        marker = Depends(lambda: None)
        assert deps._is_depends_marker(marker) is True
        assert deps._is_depends_marker(object()) is False
        assert deps._is_depends_marker(None) is False

    def test_none_uses_global(self):
        st = _make_state()
        deps.set_service_state(st)
        assert deps._resolve_state(None) is st

    def test_depends_marker_uses_global(self):
        st = _make_state()
        deps.set_service_state(st)
        marker = Depends(lambda: None)
        assert deps._resolve_state(marker) is st

    def test_valid_state_returned_directly(self):
        st = _make_state()
        assert deps._resolve_state(st) is st

    def test_no_global_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            deps._resolve_state(None)

    def test_wrong_type_raises_type_error(self):
        # B11 修复：非 ServiceState 非 None 非 Depends → TypeError，不静默回退
        with pytest.raises(TypeError, match="Expected ServiceState"):
            deps._resolve_state(object())


# --------------------------------------------------------------------------- #
# 各 getter 的 Available / 503 降级
# --------------------------------------------------------------------------- #
class TestGetters:
    GETTERS = {
        "memory_manager": "get_memory_manager",
        "async_memory_manager": "get_async_memory_manager",
        "context_manager": "get_context_manager",
        "acp_manager": "get_acp_manager",
        "llm_client": "get_llm_client",
        "secondary_router": "get_secondary_router",
        "mcp_manager": "get_mcp_manager",
        "model_router": "get_model_router",
        "asr_service": "get_asr_service",
        "tts_service": "get_tts_service",
        "document_memory_manager": "get_document_memory_manager",
    }

    @pytest.mark.parametrize("attr,getter", list(GETTERS.items()))
    def test_available(self, attr, getter):
        obj = object()
        st = _make_state(**{attr: obj})
        deps.set_service_state(st)
        assert getattr(deps, getter)() is obj

    @pytest.mark.parametrize("attr,getter", list(GETTERS.items()))
    def test_unavailable_503(self, attr, getter):
        st = _make_state()  # 该字段为 None
        deps.set_service_state(st)
        with pytest.raises(HTTPException) as exc:
            getattr(deps, getter)()
        assert exc.value.status_code == 503

    def test_get_cxfc_manager_returns_none_when_missing(self):
        st = _make_state()
        deps.set_service_state(st)
        assert deps.get_cxfc_manager() is None

    def test_get_cxfc_manager_returns_value(self):
        obj = object()
        st = _make_state(cxfc_manager=obj)
        deps.set_service_state(st)
        assert deps.get_cxfc_manager() is obj


# --------------------------------------------------------------------------- #
# per-agent 图数据库/图存储注册表
# --------------------------------------------------------------------------- #
class FakeGraphDB:
    def __init__(self, agent_id):
        self.agent_id = agent_id
        self.closed = False
        self.initialized = False

    def initialize(self):
        self.initialized = True

    def close(self):
        self.closed = True


class FakeGraphStore:
    def __init__(self, gdb=None):
        self.gdb = gdb


class TestGraphRegistry:
    def test_create_graph_database(self, monkeypatch):
        import server.core.graph as graph_mod
        monkeypatch.setattr(graph_mod, "GraphDatabase", FakeGraphDB)

        gdb = deps._get_or_create_graph_database("a1")
        assert isinstance(gdb, FakeGraphDB)
        assert gdb.agent_id == "a1"
        assert gdb.initialized is True
        # 幂等：再次调用返回同一实例，不重复初始化
        gdb2 = deps._get_or_create_graph_database("a1")
        assert gdb2 is gdb

    def test_graph_store_uses_same_db(self, monkeypatch):
        import server.core.graph as graph_mod
        import server.core.memory.graph_store as gs_mod
        monkeypatch.setattr(graph_mod, "GraphDatabase", FakeGraphDB)
        monkeypatch.setattr(gs_mod, "SQLiteGraphStore", FakeGraphStore)

        store = deps._get_or_create_graph_store("a1")
        assert isinstance(store, FakeGraphStore)
        store2 = deps._get_or_create_graph_store("a1")
        assert store2 is store

    def test_per_agent_isolation(self, monkeypatch):
        import server.core.graph as graph_mod
        monkeypatch.setattr(graph_mod, "GraphDatabase", FakeGraphDB)
        g1 = deps._get_or_create_graph_database("x")
        g2 = deps._get_or_create_graph_database("y")
        assert g1 is not g2
        assert g1.agent_id == "x"
        assert g2.agent_id == "y"

    def test_remove_graph_database_clears_and_closes(self, monkeypatch):
        import server.core.graph as graph_mod
        monkeypatch.setattr(graph_mod, "GraphDatabase", FakeGraphDB)

        gdb = deps._get_or_create_graph_database("a1")
        deps.remove_graph_database("a1")
        assert "a1" not in deps._graph_databases
        assert "a1" not in deps._graph_stores
        assert gdb.closed is True

    def test_remove_graph_database_missing_no_error(self):
        deps.remove_graph_database("missing")  # 不应抛异常

    def test_double_check_lock_serialization(self, monkeypatch):
        import server.core.graph as graph_mod
        monkeypatch.setattr(graph_mod, "GraphDatabase", FakeGraphDB)

        results = []
        errors = []

        def worker():
            try:
                results.append(deps._get_or_create_graph_database("shared"))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(results) == 8
        # 全部线程返回同一实例（双重检查锁保证单例）
        assert all(r is results[0] for r in results)


class TestCloseAllGraphDatabasesResilience:
    """E11: 逐实例 close 抛异常时仍清空注册表、不抛出且有 warning 留痕。"""

    def test_close_exception_still_clears_registry_and_logs(self, monkeypatch, caplog):
        import logging

        import server.core.graph as graph_mod

        class BoomGraphDB(FakeGraphDB):
            def close(self):
                raise RuntimeError("close 失败")

        monkeypatch.setattr(graph_mod, "GraphDatabase", BoomGraphDB)
        deps._get_or_create_graph_database("boom")
        assert "boom" in deps._graph_databases

        # 不应抛出（幂等语义保持：调用后注册表必须已清空）
        with caplog.at_level(logging.WARNING):
            deps.close_all_graph_databases()

        assert "boom" not in deps._graph_databases
        assert "boom" not in deps._graph_stores
        # close 失败有 warning 留痕
        assert any(
            r.levelno == logging.WARNING and "boom" in r.getMessage()
            for r in caplog.records
        )
