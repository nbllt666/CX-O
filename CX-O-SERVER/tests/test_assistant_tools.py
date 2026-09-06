"""server.core.tools.assistant_tools 单元测试。

覆盖记忆管理模型工具：记忆修改/搜索/软删除/统计/按标签搜索/批量删除/恢复、
聊天记录读取、可用命令获取。外部依赖（记忆管理器、上下文管理器、副模型
路由器）以轻量替身注入；`Settings` 默认值路径用 monkeypatch 隔离。

运行：python -m pytest tests/test_assistant_tools.py -v
"""
import pytest

import server.core.tools.assistant_tools as at
from server.core.tools.registry import tool_registry


# ---------------------------------------------------------------- 依赖替身
class FakeMemoryManager:
    def __init__(self):
        self.update_result = True
        self.search_results = []
        self.delete_result = True
        self.delete_calls = []
        self.stats = {}
        self.batch_result = {"success": 1, "failed": 2, "deleted_ids": [11]}
        self.batch_calls = []
        self.restore_result = True
        self.memories = {}  # memory_id -> 记忆 dict（供人格保护闸门读取）

    def update_memory(self, memory_id, new_content):
        return self.update_result

    def search_memories(self, query=None, time_range=None, limit=None, tags=None):
        return self.search_results

    def get_memory(self, memory_id, include_deleted=False):
        return self.memories.get(int(memory_id))

    def delete_memory(self, memory_id, soft_delete):
        self.delete_calls.append(memory_id)
        return self.delete_result

    def get_statistics(self):
        return self.stats

    def batch_delete_memories(self, memory_ids, soft_delete):
        self.batch_calls.append(list(memory_ids))
        return self.batch_result

    def restore_memory(self, memory_id):
        return self.restore_result


class FakeContextManager:
    def __init__(self):
        self.messages = []

    def get_messages(self, session_id, limit):
        return self.messages

    def get_recent_messages(self, session_id, limit):
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


# ------------------------------------------------- 遗忘语义改造（人格保护闸门）
class TestDeleteMemoryForgetSemantics:
    """delete_memory 遗忘语义：注册描述、闸门拒绝路径与成功提示。"""

    def test_registration_forget_description(self, clean_deps):
        """注册描述为遗忘语义，无"7天自动清理"表述。"""
        at.register_assistant_tools()
        tool = tool_registry.get_tool("delete_memory")
        assert "遗忘" in tool.description
        assert "永不物理清除" in tool.description
        assert "restore_memory" in tool.description
        assert "7天" not in tool.description
        assert "7 天" not in tool.description

    def test_registration_tags_and_examples(self, clean_deps):
        at.register_assistant_tools()
        tool = tool_registry.get_tool("delete_memory")
        assert tool.tags == ["memory", "forget", "soft_delete"]
        assert tool.examples and "遗忘" in tool.examples[0]

    def test_guard_rejection_permanent(self, clean_deps):
        """永久记忆被真实闸门拒绝，返回保护原因且未执行删除。"""
        mm = FakeMemoryManager()
        mm.memories = {1: {"id": 1, "content": "人格核心记忆", "permanent": 1}}
        _set_mm(mm)
        r = at.delete_memory("1", "x")
        assert "error" in r
        assert "人格核心" in r["error"]
        assert mm.delete_calls == []

    def test_guard_rejection_reason_passthrough(self, clean_deps, monkeypatch):
        """闸门拒绝时原因透传到 error 字段。"""
        mm = FakeMemoryManager()
        mm.memories = {2: {"id": 2, "content": "普通记忆"}}
        _set_mm(mm)
        monkeypatch.setattr(
            at,
            "evaluate_persona_guard",
            lambda m: {"allowed": False, "reason": "自定义保护原因"},
        )
        r = at.delete_memory("2", "x")
        assert r == {"error": "自定义保护原因"}
        assert mm.delete_calls == []

    def test_success_message_mentions_restore_and_hard_delete(self, clean_deps, monkeypatch):
        """放行后成功返回含"可随时恢复"与"REST API 显式硬删"提示。"""
        mm = FakeMemoryManager()
        mm.memories = {1: {"id": 1, "content": "普通记忆"}}
        _set_mm(mm)
        monkeypatch.setattr(
            at, "evaluate_persona_guard", lambda m: {"allowed": True, "reason": ""}
        )
        r = at.delete_memory("1", "过时")
        assert r["status"] == "deleted"
        assert "可随时恢复" in r["message"]
        assert "REST API 显式硬删" in r["message"]
        assert mm.delete_calls == [1]

    def test_memory_not_found_skips_guard(self, clean_deps, monkeypatch):
        """记忆不存在时跳过闸门，交由原删除逻辑处理（failed 路径）。"""
        guard_called = []
        monkeypatch.setattr(
            at, "evaluate_persona_guard", lambda m: guard_called.append(m)
        )
        mm = FakeMemoryManager()  # memories 为空 → get_memory 返回 None
        mm.delete_result = False
        _set_mm(mm)
        r = at.delete_memory("99", "x")
        assert guard_called == []
        assert r["status"] == "failed"


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
        assert "批量遗忘失败" in r["error"]


# ------------------------------------------------- 批量遗忘分桶（人格保护闸门）
class TestBulkDeleteForgetSemantics:
    """bulk_delete 遗忘语义：注册描述、protected/forgotten 分桶。"""

    def test_registration_forget_description(self, clean_deps):
        """注册描述为批量遗忘语义，说明受保护记忆将被跳过。"""
        at.register_assistant_tools()
        tool = tool_registry.get_tool("bulk_delete")
        assert "批量遗忘" in tool.description
        assert "永不物理清除" in tool.description
        assert "protected" in tool.description

    def test_registration_tags_and_examples(self, clean_deps):
        at.register_assistant_tools()
        tool = tool_registry.get_tool("bulk_delete")
        assert tool.tags == ["memory", "forget", "bulk", "batch"]
        assert tool.examples and "遗忘" in tool.examples[0]

    def test_buckets_with_monkeypatched_guard(self, clean_deps, monkeypatch):
        """放行 id 走批量软删并列入 forgotten；受保护 id 跳过并列入 protected。"""
        mm = FakeMemoryManager()
        mm.memories = {1: {"id": 1, "content": "受保护"}, 2: {"id": 2, "content": "普通"}}
        mm.batch_result = {"success": 1, "failed": 0, "deleted_ids": [2]}
        _set_mm(mm)
        monkeypatch.setattr(
            at,
            "evaluate_persona_guard",
            lambda m: (
                {"allowed": False, "reason": f"保护原因-{m['id']}"}
                if m["id"] == 1
                else {"allowed": True, "reason": ""}
            ),
        )
        r = at.bulk_delete(["1", "2"], "x")
        assert r["status"] == "completed"
        assert r["forgotten"] == [2]
        assert r["protected"] == [{"memory_id": "1", "reason": "保护原因-1"}]
        assert r["deleted_count"] == 1
        assert r["failed_count"] == 0
        assert mm.batch_calls == [[2]]

    def test_permanent_protection_with_real_guard(self, clean_deps):
        """真实闸门集成：永久记忆进入 protected，普通记忆进入 forgotten。"""
        mm = FakeMemoryManager()
        mm.memories = {1: {"id": 1, "content": "人格核心", "permanent": 1}, 2: {"id": 2}}
        mm.batch_result = {"success": 1, "failed": 0, "deleted_ids": [2]}
        _set_mm(mm)
        r = at.bulk_delete(["1", "2"], "x")
        assert [p["memory_id"] for p in r["protected"]] == ["1"]
        assert "人格核心" in r["protected"][0]["reason"]
        assert r["forgotten"] == [2]

    def test_memory_not_found_skips_guard(self, clean_deps, monkeypatch):
        """不存在的记忆跳过闸门，交由原批量逻辑统一计为 failed。"""
        guard_called = []
        monkeypatch.setattr(
            at, "evaluate_persona_guard", lambda m: guard_called.append(m)
        )
        mm = FakeMemoryManager()
        _set_mm(mm)
        r = at.bulk_delete(["1", "2"], "x")
        assert guard_called == []
        assert r["deleted_count"] == 1
        assert r["failed_count"] == 2
        assert r["protected"] == []


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

            def get_recent_messages(self, session_id, limit):
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