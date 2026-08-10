"""server.core.tools.assistant_tools 单元测试。

覆盖记忆管理模型工具：记忆修改/搜索/软删除/统计/按标签搜索/批量删除/恢复、
聊天记录读取、可用命令获取。外部依赖（记忆管理器、上下文管理器、副模型
路由器）以轻量替身注入；`Settings` 默认值路径用 monkeypatch 隔离。

运行：python -m pytest tests/test_assistant_tools.py -v
"""
import pytest

import server.core.tools.assistant_tools as at


# ---------------------------------------------------------------- 依赖替身
class FakeMemoryManager:
    def __init__(self):
        self.update_result = True
        self.search_results = []
        self.delete_result = True
        self.stats = {}
        self.batch_result = {"success": 1, "failed": 2}
        self.restore_result = True

    def update_memory(self, memory_id, new_content):
        return self.update_result

    def search_memories(self, query=None, time_range=None, limit=None, tags=None):
        return self.search_results

    def delete_memory(self, memory_id, soft_delete):
        return self.delete_result

    def get_statistics(self):
        return self.stats

    def batch_delete_memories(self, memory_ids, soft_delete):
        return self.batch_result

    def restore_memory(self, memory_id):
        return self.restore_result


class FakeContextManager:
    def __init__(self):
        self.messages = []

    def get_messages(self, session_id, limit):
        return self.messages


class FakeRouter:
    def __init__(self):
        self.commands = ["cmd1"]

    def get_available_commands(self):
        return self.commands


@pytest.fixture
def clean_deps():
    at.set_dependencies(None, None, None)
    yield
    at.set_dependencies(None, None, None)


def _set_mm(mm):
    at.set_dependencies(memory_manager=mm)


def _set_cm(cm):
    at.set_dependencies(context_manager=cm)


def _set_router(router):
    at.set_dependencies(secondary_router=router)


# ---------------------------------------------------------------- 记忆修改
class TestUpdateMemoryNode:
    def test_no_manager(self, clean_deps):
        assert at.update_memory_node("1", "x") == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        r = at.update_memory_node("1", "新内容")
        assert r["status"] == "updated"
        assert r["memory_id"] == "1"
        assert r["new_content_preview"] == "新内容"

    def test_failed(self, clean_deps):
        mm = FakeMemoryManager()
        mm.update_result = False
        _set_mm(mm)
        assert at.update_memory_node("1", "x")["status"] == "failed"

    def test_exception(self, clean_deps):
        class Boom:
            def update_memory(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = at.update_memory_node("1", "x")
        assert "修改记忆失败" in r["error"]


# ---------------------------------------------------------------- 记忆搜索
class TestSearchMemories:
    def test_no_manager(self, clean_deps):
        assert at.search_memories("q", limit=5) == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        mm.search_results = [{"id": "1", "content": "a" * 300, "importance": 3, "created_at": "t"}]
        _set_mm(mm)
        r = at.search_memories("q", time_range="last_week", limit=5)
        assert r["count"] == 1
        assert r["memories"][0]["id"] == "1"
        assert r["memories"][0]["content"] == "a" * 200  # 截断到 200

    def test_default_limit(self, clean_deps, monkeypatch):
        class FakeSettings:
            class limits:
                class memory:
                    search_memories_limit = 42

            config = type("cfg", (), {"limits": type("l", (), {"memory": limits.memory})})()

        monkeypatch.setattr("server.core.tools.assistant_tools.Settings", lambda: FakeSettings())
        mm = FakeMemoryManager()
        _set_mm(mm)
        at.search_memories("q")
        assert mm.search_results == []

    def test_exception(self, clean_deps):
        class Boom:
            def search_memories(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = at.search_memories("q", limit=5)
        assert "搜索记忆失败" in r["error"]


# ---------------------------------------------------------------- 记忆删除
class TestDeleteMemory:
    def test_no_manager(self, clean_deps):
        r = at.delete_memory("1", "错误信息")
        assert r == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        r = at.delete_memory("1", "过时")
        assert r["status"] == "deleted"
        assert r["soft_delete"] is True
        assert r["reason"] == "过时"

    def test_failed(self, clean_deps):
        mm = FakeMemoryManager()
        mm.delete_result = False
        _set_mm(mm)
        assert at.delete_memory("1", "x")["status"] == "failed"


# ---------------------------------------------------------------- 统计
class TestMemoryStats:
    def test_no_manager(self, clean_deps):
        assert at.get_memory_stats() == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        mm.stats = {"total": 10}
        _set_mm(mm)
        assert at.get_memory_stats() == {"total": 10}

    def test_exception(self, clean_deps):
        class Boom:
            def get_statistics(self):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = at.get_memory_stats()
        assert "获取统计失败" in r["error"]


# ---------------------------------------------------------------- 按标签
class TestSearchByTag:
    def test_no_manager(self, clean_deps):
        assert at.search_by_tag(["重要"]) == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        mm.search_results = [{"id": "1", "content": "c", "tags": ["重要"]}]
        _set_mm(mm)
        r = at.search_by_tag(["重要"])
        assert r["count"] == 1
        assert r["memories"][0]["tags"] == ["重要"]

    def test_exception(self, clean_deps):
        class Boom:
            def search_memories(self, tags=None):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = at.search_by_tag(["重要"])
        assert "按标签搜索失败" in r["error"]


# ---------------------------------------------------------------- 批量删除
class TestBulkDelete:
    def test_no_manager(self, clean_deps):
        r = at.bulk_delete(["1", "2"], "批量清理")
        assert r == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        r = at.bulk_delete(["1", "2"], "x")
        assert r["status"] == "completed"
        assert r["deleted_count"] == 1
        assert r["failed_count"] == 2

    def test_exception(self, clean_deps):
        class Boom:
            def batch_delete_memories(self, **kw):
                raise RuntimeError("boom")

        _set_mm(Boom())
        r = at.bulk_delete(["1", "2"], "x")
        assert "批量删除失败" in r["error"]


# ---------------------------------------------------------------- 恢复
class TestRestoreMemory:
    def test_no_manager(self, clean_deps):
        assert at.restore_memory("1") == {"error": "记忆管理器不可用"}

    def test_success(self, clean_deps):
        mm = FakeMemoryManager()
        _set_mm(mm)
        r = at.restore_memory("1")
        assert r["status"] == "restored"

    def test_failed(self, clean_deps):
        mm = FakeMemoryManager()
        mm.restore_result = False
        _set_mm(mm)
        assert at.restore_memory("1")["status"] == "failed"


# ---------------------------------------------------------------- 聊天记录
class TestGetChatHistory:
    def test_no_context_manager(self, clean_deps):
        r = at.get_chat_history("s1", limit=5)
        assert r == {"error": "上下文管理器不可用"}

    def test_success(self, clean_deps):
        cm = FakeContextManager()
        cm.messages = [{"id": "m1"}]
        _set_cm(cm)
        r = at.get_chat_history("s1", limit=5)
        assert r["count"] == 1
        assert r["session_id"] == "s1"

    def test_default_limit(self, clean_deps, monkeypatch):
        class FakeSettings:
            class limits:
                class memory:
                    chat_history_limit = 9

            config = type("cfg", (), {"limits": type("l", (), {"memory": limits.memory})})()

        monkeypatch.setattr("server.core.tools.assistant_tools.Settings", lambda: FakeSettings())
        cm = FakeContextManager()
        _set_cm(cm)
        at.get_chat_history("s1")
        assert cm.messages == []

    def test_exception(self, clean_deps):
        class Boom:
            def get_messages(self, session_id, limit):
                raise RuntimeError("boom")

        _set_cm(Boom())
        r = at.get_chat_history("s1", limit=5)
        assert "读取聊天记录失败" in r["error"]


# ---------------------------------------------------------------- 可用命令
class TestGetAvailableCommands:
    def test_no_router(self, clean_deps):
        assert at.get_available_commands() == {"error": "副模型路由器不可用"}

    def test_success(self, clean_deps):
        router = FakeRouter()
        _set_router(router)
        r = at.get_available_commands()
        assert r["status"] == "success"
        assert r["commands"] == ["cmd1"]

    def test_exception(self, clean_deps):
        class Boom:
            def get_available_commands(self):
                raise RuntimeError("boom")

        _set_router(Boom())
        r = at.get_available_commands()
        assert "获取可用命令失败" in r["error"]