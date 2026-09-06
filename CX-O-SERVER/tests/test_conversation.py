"""server.core.memory.conversation (MemoryConversationEngine) 单元测试。

覆盖命令解析、参数提取、确认流程、各命令处理器与通用回复降级。
运行：python -m pytest tests/test_conversation.py -v
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from server.core.memory.conversation import (
    MemoryCommand,
    MemoryConversationEngine,
)


@dataclass
class FakeArchiveResult:
    memory_id: int
    target_level: int

    def to_dict(self) -> Dict[str, Any]:
        return {"memory_id": self.memory_id, "target_level": self.target_level}


class FakeArchiver:
    def __init__(self):
        self.archive_calls = []
        self.merge_calls = []

    async def archive_memory(self, memory_id, target_level):
        self.archive_calls.append((memory_id, target_level))
        return FakeArchiveResult(memory_id=memory_id, target_level=target_level)

    async def merge_duplicate_memories(self, memory_ids, strategy):
        self.merge_calls.append((memory_ids, strategy))
        return _MergeResult(success=True, message="合并成功", merged_memory_id=1, merged_from=memory_ids)

    def get_archive_stats(self):
        return {"total_archived": 3, "merge_count": 1, "duplicate_count": 2}


@dataclass
class _MergeResult:
    success: bool
    message: str
    merged_memory_id: int
    merged_from: List[int]


class FakeDedupEngine:
    def __init__(self, groups=None):
        self.groups = groups or []

    async def detect_duplicates_batch(self, threshold=0.85):
        return self.groups


class FakeMemoryManager:
    def __init__(self):
        self.memories: List[Dict[str, Any]] = []
        self.archiver = None
        self.deduplication_engine = None
        self.deleted: List[int] = []

    def add(self, mid, content, mtype="long_term", permanent=False, is_archived=False):
        self.memories.append(
            {
                "id": mid,
                "content": content,
                "type": mtype,
                "importance": 3,
                "permanent": permanent,
                "is_archived": is_archived,
            }
        )

    def search_memories(self, query=None, memory_type=None, limit=10, include_deleted=False):
        results = self.memories
        if memory_type:
            results = [m for m in results if m.get("type") == memory_type]
        if query:
            results = [m for m in results if query in m.get("content", "")]
        return results[:limit]

    async def get_memory_async(self, memory_id, include_deleted=False):
        for m in self.memories:
            if m.get("id") == memory_id:
                return m
        return None

    async def delete_memory_async(self, memory_id, soft_delete=True):
        self.deleted.append(memory_id)
        return True


class FakeLLM:
    def __init__(self, text="这是通用回复"):
        self.text = text
        self.calls = 0

    async def generate(self, prompt):
        self.calls += 1
        return {"text": self.text}


@pytest.fixture
def engine():
    mgr = FakeMemoryManager()
    return MemoryConversationEngine(memory_manager=mgr)


@pytest.fixture
def mgr(engine):
    return engine.memory_manager


class TestSerialization:
    def test_command_to_fields(self):
        c = MemoryCommand("search", {"query": "x"}, 0.8, True, "搜索记忆")
        assert c.command_type == "search"
        assert c.parameters == {"query": "x"}
        assert c.confidence == 0.8
        assert c.requires_confirmation is True
        assert c.description == "搜索记忆"

    def test_unknown_defaults(self):
        c = MemoryCommand("unknown")
        assert c.parameters == {}
        assert c.confidence == 0.0
        assert c.requires_confirmation is False


class TestSession:
    def test_get_or_create(self, engine):
        ctx = engine.get_or_create_session("s1")
        assert ctx.session_id == "s1"
        assert engine.get_or_create_session("s1") is ctx

    def test_distinct_sessions(self, engine):
        a = engine.get_or_create_session("a")
        b = engine.get_or_create_session("b")
        assert a is not b


class TestParseCommand:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("搜索关于人工智能的记忆", "search"),
            ("find python", "search"),
            ("归档记忆 ID 123", "archive"),
            ("合并重复记忆", "merge"),
            ("删除记忆 ID 789", "delete"),
            ("更新记忆", "update"),
            ("检测重复记忆", "deduplicate"),
            ("查看统计", "stats"),
            ("帮助", "help"),
            ("随便聊聊今天的天气", "unknown"),
        ],
    )
    @pytest.mark.asyncio
    async def test_command_detection(self, engine, text, expected):
        ctx = engine.get_or_create_session("s")
        cmd = await engine._parse_command(text, ctx)
        assert cmd.command_type == expected

    @pytest.mark.asyncio
    async def test_destructive_requires_confirmation(self, engine):
        ctx = engine.get_or_create_session("s")
        for cmd_type in ["delete", "merge", "archive"]:
            cmd = await engine._parse_command(f"{cmd_type} something", ctx)
            assert cmd.requires_confirmation is True

    @pytest.mark.asyncio
    async def test_non_destructive_no_confirmation(self, engine):
        ctx = engine.get_or_create_session("s")
        cmd = await engine._parse_command("search x", ctx)
        assert cmd.requires_confirmation is False


class TestExtractParameters:
    def test_search_query(self, engine):
        p = engine._extract_parameters("搜索关于AI的记忆", "search")
        assert p["query"] == "关于AI的记忆"

    def test_search_permanent(self, engine):
        p = engine._extract_parameters("查找所有永久记忆", "search")
        assert p["memory_type"] == "permanent"

    def test_search_limit(self, engine):
        p = engine._extract_parameters("找一下最近的10条记忆", "search")
        assert p["limit"] == 10

    def test_archive_level_and_id(self, engine):
        p = engine._extract_parameters("归档记忆 ID 123 到级别 2", "archive")
        assert p["memory_id"] == 123
        assert p["target_level"] == 2

    def test_archive_default_level(self, engine):
        p = engine._extract_parameters("归档记忆 ID 5", "archive")
        assert p["target_level"] == 1

    def test_merge_ids(self, engine):
        p = engine._extract_parameters("合并记忆 1 和记忆 2", "merge")
        assert p["memory_ids"] == [1, 2]

    def test_delete_id(self, engine):
        p = engine._extract_parameters("删除记忆 ID 789", "delete")
        assert p["memory_id"] == 789


class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_unknown_without_llm(self, engine):
        r = await engine.process_message("随便聊聊", session_id="s")
        assert r["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_unknown_with_llm(self, engine, mgr):
        engine.llm_client = FakeLLM()
        r = await engine.process_message("随便聊聊", session_id="s")
        assert r["status"] == "success"
        assert r["message"] == "这是通用回复"

    @pytest.mark.asyncio
    async def test_search_success(self, engine, mgr):
        mgr.add(1, "关于人工智能的记忆")
        r = await engine.process_message("搜索关于人工智能的记忆", session_id="s")
        assert r["status"] == "success"
        assert r["count"] == 1
        assert r["results"][0]["id"] == 1

    @pytest.mark.asyncio
    async def test_search_empty(self, engine, mgr):
        r = await engine.process_message("搜索不存在的东西", session_id="s")
        assert r["status"] == "success"
        assert r["results"] == []

    @pytest.mark.asyncio
    async def test_help(self, engine):
        r = await engine.process_message("帮助", session_id="s")
        assert r["status"] == "success"
        assert "可用命令" in r["message"]

    @pytest.mark.asyncio
    async def test_stats(self, engine, mgr):
        mgr.add(1, "a", mtype="long_term")
        mgr.add(2, "b", mtype="short_term", permanent=True)
        r = await engine.process_message("查看统计", session_id="s")
        assert r["status"] == "success"
        assert r["stats"]["total"] == 2
        assert r["stats"]["permanent"] == 1

    @pytest.mark.asyncio
    async def test_update_returns_info(self, engine):
        r = await engine.process_message("更新记忆", session_id="s")
        assert r["status"] == "info"


class TestConfirmationFlow:
    @pytest.mark.asyncio
    async def test_delete_confirm_and_execute(self, engine, mgr):
        mgr.add(1, "待删除记忆")
        r1 = await engine.process_message("删除记忆 ID 1", session_id="s")
        assert r1["status"] == "waiting_confirmation"
        r2 = await engine.process_message("是", session_id="s")
        assert r2["status"] == "success"
        assert mgr.deleted == [1]

    @pytest.mark.asyncio
    async def test_delete_cancel(self, engine, mgr):
        mgr.add(1, "待删除记忆")
        await engine.process_message("删除记忆 ID 1", session_id="s")
        r = await engine.process_message("否", session_id="s")
        assert r["status"] == "cancelled"
        assert mgr.deleted == []

    @pytest.mark.asyncio
    async def test_confirmation_waiting_again(self, engine, mgr):
        mgr.add(1, "记忆")
        await engine.process_message("删除记忆 ID 1", session_id="s")
        r = await engine.process_message("随便说点什么", session_id="s")
        assert r["status"] == "waiting_confirmation"

    @pytest.mark.asyncio
    async def test_archive_confirmation(self, engine, mgr):
        mgr.archiver = FakeArchiver()
        mgr.add(2, "待归档")
        await engine.process_message("归档记忆 ID 2", session_id="s")
        r = await engine.process_message("确认", session_id="s")
        assert r["status"] == "success"
        assert mgr.archiver.archive_calls == [(2, 1)]

    @pytest.mark.asyncio
    async def test_archive_without_archiver(self, engine, mgr):
        mgr.add(2, "待归档")
        # 无确认参数时直接执行，但 archiver 为 None
        r = await engine.process_message("归档记忆 ID 2", session_id="s")
        assert r["status"] == "waiting_confirmation"
        r2 = await engine.process_message("是", session_id="s")
        assert r2["status"] == "error"


class TestDedupHandler:
    @pytest.mark.asyncio
    async def test_dedup_no_groups(self, engine, mgr):
        mgr.deduplication_engine = FakeDedupEngine(groups=[])
        r = await engine.process_message("检测重复记忆", session_id="s")
        assert r["status"] == "success"
        assert r["groups"] == []

    @pytest.mark.asyncio
    async def test_dedup_with_groups(self, engine, mgr):
        from server.core.memory.deduplication import DuplicateGroup

        group = DuplicateGroup(group_id="g1", memory_ids=[1, 2], canonical_id=1)
        mgr.deduplication_engine = FakeDedupEngine(groups=[group])
        r = await engine.process_message("检测重复记忆", session_id="s")
        assert r["status"] == "success"
        assert len(r["groups"]) == 1

    @pytest.mark.asyncio
    async def test_dedup_disabled(self, engine, mgr):
        r = await engine.process_message("检测重复记忆", session_id="s")
        assert r["status"] == "error"


class TestMergeHandler:
    @pytest.mark.asyncio
    async def test_merge_executes(self, engine, mgr):
        mgr.archiver = FakeArchiver()
        # 确认流程
        await engine.process_message("合并记忆 1 和记忆 2", session_id="s")
        r = await engine.process_message("是", session_id="s")
        assert r["status"] == "success"
        assert mgr.archiver.merge_calls[0][0] == [1, 2]

    @pytest.mark.asyncio
    async def test_merge_less_than_two(self, engine, mgr):
        r = await engine.process_message("合并记忆 1", session_id="s")
        assert r["status"] == "waiting_confirmation"
        r2 = await engine.process_message("是", session_id="s")
        assert r2["status"] == "error", r2["message"]


class TestForgetSemantics:
    """遗忘语义改造：删除/合并话术去破坏化、人格保护闸门与帮助文本。"""

    @pytest.mark.asyncio
    async def test_delete_confirmation_forget_semantics(self, engine, mgr):
        """确认话术为遗忘语义：可恢复、含归档替代建议、不含"无法恢复"。"""
        mgr.add(1, "普通记忆")
        r = await engine.process_message("删除记忆 ID 1", session_id="s")
        assert r["status"] == "waiting_confirmation"
        assert "遗忘" in r["message"]
        assert "可随时恢复" in r["message"]
        assert "归档" in r["message"]
        assert "无法恢复" not in r["message"]

    @pytest.mark.asyncio
    async def test_delete_success_forget_message(self, engine, mgr):
        """成功话术："已遗忘（软删除），可随时恢复"。"""
        mgr.add(1, "普通记忆")
        await engine.process_message("删除记忆 ID 1", session_id="s")
        r = await engine.process_message("是", session_id="s")
        assert r["status"] == "success"
        assert "已遗忘" in r["message"]
        assert "可随时恢复" in r["message"]

    @pytest.mark.asyncio
    async def test_delete_guard_rejection_permanent(self, engine, mgr):
        """永久记忆被人格保护闸门拒绝，返回保护原因且未执行删除。"""
        mgr.add(1, "人格核心记忆", permanent=True)
        await engine.process_message("删除记忆 ID 1", session_id="s")
        r = await engine.process_message("是", session_id="s")
        assert r["status"] == "error"
        assert "人格核心" in r["message"]
        assert mgr.deleted == []

    @pytest.mark.asyncio
    async def test_delete_guard_rejection_reason_passthrough(self, engine, mgr, monkeypatch):
        """闸门拒绝原因透传到 message（monkeypatch 闸门验证接线）。"""
        from server.core.memory import conversation as conv

        mgr.add(1, "普通记忆")
        monkeypatch.setattr(
            conv,
            "evaluate_persona_guard",
            lambda m: {"allowed": False, "reason": "自定义保护原因"},
        )
        await engine.process_message("删除记忆 ID 1", session_id="s")
        r = await engine.process_message("是", session_id="s")
        assert r["status"] == "error"
        assert r["message"] == "自定义保护原因"
        assert mgr.deleted == []

    @pytest.mark.asyncio
    async def test_merge_confirmation_traceable(self, engine, mgr):
        """合并确认话术：无"无法撤销"，含"保留原文/审计/可回溯"。"""
        mgr.archiver = FakeArchiver()
        r = await engine.process_message("合并记忆 1 和记忆 2", session_id="s")
        assert r["status"] == "waiting_confirmation"
        assert "无法撤销" not in r["message"]
        assert "保留原文" in r["message"]
        assert "审计" in r["message"]
        assert "可回溯" in r["message"]

    @pytest.mark.asyncio
    async def test_help_contains_forget_and_persona_note(self, engine):
        """帮助文本：第4条为遗忘记忆，注意事项含人格保护说明。"""
        r = await engine.process_message("帮助", session_id="s")
        assert r["status"] == "success"
        assert "遗忘记忆" in r["message"]
        assert '"遗忘记忆 ID 789"' in r["message"]
        assert "人格保护" in r["message"]
        assert "归档" in r["message"]