"""
server/handlers/memory.py 回归测试
记忆处理器：LIST/CREATE/DELETE/SEARCH（含向量检索分支与降级）
"""
from types import SimpleNamespace

import pytest

import server.dependencies as deps
from server.handlers.memory import register_memory_handlers
from server.protocol.actions import MemoryActions


class FakeMemoryMgr:
    def __init__(self):
        self.calls = []
        self.vector = False
        self.search_result = [{"id": 1}]
        self.memory_id = "mem-1"
        self.delete_success = True

    def is_vector_search_enabled(self):
        return self.vector

    async def search_memories_async(self, **kw):
        self.calls.append(("search_async", kw))
        return self.search_result

    async def write_memory_async(self, **kw):
        self.calls.append(("write", kw))
        return self.memory_id

    async def delete_memory_async(self, **kw):
        self.calls.append(("delete", kw))
        return self.delete_success

    def search_memories(self, **kw):
        self.calls.append(("search", kw))
        return self.search_result

    async def hybrid_search(self, **kw):
        self.calls.append(("hybrid", kw))
        return self.search_result


class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []

    def register_handler(self, action, handler):
        self.handlers[action] = handler

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


@pytest.fixture
def mgr():
    return FakeManager()


@pytest.fixture
def handlers(mgr):
    register_memory_handlers(mgr)
    return mgr.handlers


@pytest.fixture
def mm():
    return FakeMemoryMgr()


def _patch(monkeypatch, mm):
    monkeypatch.setattr(deps, "get_memory_manager", lambda: mm)


def _err(mgr):
    msg = mgr.sent[-1][1]
    assert msg["type"] == "error"
    return msg["error"]["code"], msg["error"]["message"]


class TestMemoryHandlers:
    @pytest.mark.asyncio
    async def test_list(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MemoryActions.LIST](
            None, {"request_id": "r1", "data": {"query": "q", "limit": 5}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["action"] == MemoryActions.LIST
        assert msg["data"]["memories"] == [{"id": 1}]
        kw = mm.calls[0][1]
        assert kw["query"] == "q"
        assert kw["limit"] == 5
        assert kw["workspace_id"] == "default"

    @pytest.mark.asyncio
    async def test_create(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MemoryActions.CREATE](
            None, {"data": {"content": "hi", "type": "long_term"}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"memory_id": "mem-1"}
        kw = mm.calls[0][1]
        assert kw["content"] == "hi"
        assert kw["importance"] == 3

    @pytest.mark.asyncio
    async def test_delete(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MemoryActions.DELETE](
            None, {"data": {"memory_id": "m1", "soft_delete": False}}, "c1")
        assert mgr.sent[-1][1]["data"] == {"success": True}
        assert mm.calls[0][1]["memory_id"] == "m1"
        assert mm.calls[0][1]["soft_delete"] is False

    @pytest.mark.asyncio
    async def test_search_regular(self, handlers, mgr, mm, monkeypatch):
        _patch(monkeypatch, mm)
        await handlers[MemoryActions.SEARCH](None, {"data": {"query": "q"}}, "c1")
        assert mgr.sent[-1][1]["data"]["memories"] == [{"id": 1}]
        # 非语义分支已切换为异步变体 search_memories_async（不再同步直调）
        assert mm.calls[0][0] == "search_async"

    @pytest.mark.asyncio
    async def test_search_vector(self, handlers, mgr, mm, monkeypatch):
        mm.vector = True
        _patch(monkeypatch, mm)
        await handlers[MemoryActions.SEARCH](
            None, {"data": {"query": "q", "semantic": True}}, "c1")
        assert mm.calls[0][0] == "hybrid"
        assert mgr.sent[-1][1]["data"]["memories"] == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_search_vector_error(self, handlers, mgr, mm, monkeypatch):
        mm.vector = True

        async def bad(**kw):
            raise RuntimeError("vec down")

        mm.hybrid_search = bad
        _patch(monkeypatch, mm)
        await handlers[MemoryActions.SEARCH](None, {"data": {"query": "q", "semantic": True}}, "c1")
        code, message = _err(mgr)
        assert code == "MEMORY_ERROR"
        assert "Vector search failed" in message

    @pytest.mark.asyncio
    async def test_search_regular_async_variant(self, handlers, mgr, mm, monkeypatch):
        """非语义分支必须走 search_memories_async 异步变体，且参数逐项透传不变。"""
        _patch(monkeypatch, mm)
        await handlers[MemoryActions.SEARCH](
            None,
            {
                "data": {
                    "query": "q",
                    "type": "long_term",
                    "tags": ["t1"],
                    "time_range": "7d",
                    "limit": 7,
                    "offset": 2,
                    "workspace_id": "ws1",
                    "agent_id": "a1",
                }
            },
            "c1",
        )
        assert mgr.sent[-1][1]["data"]["memories"] == [{"id": 1}]
        assert mm.calls[0][0] == "search_async"
        kw = mm.calls[0][1]
        assert kw["query"] == "q"
        assert kw["memory_type"] == "long_term"
        assert kw["tags"] == ["t1"]
        assert kw["time_range"] == "7d"
        assert kw["limit"] == 7
        assert kw["offset"] == 2
        assert kw["workspace_id"] == "ws1"
        assert kw["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_manager_error(self, handlers, mgr, monkeypatch):
        def boom():
            raise RuntimeError("no memory mgr")

        monkeypatch.setattr(deps, "get_memory_manager", boom)
        await handlers[MemoryActions.LIST](None, {}, "c1")
        code, _ = _err(mgr)
        assert code == "MEMORY_ERROR"