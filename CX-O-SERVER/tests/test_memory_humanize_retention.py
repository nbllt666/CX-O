"""记忆人性化保留（humanize-memory-agent-retention）回归测试。

覆盖 spec P1-B 组（Task 4 + Task 5）改动：
  1. cleanup_memories 归档化——低分记忆归档到深度归档级别（target_level=4），
     遗忘≠删除（不再调用 batch_delete_memories）；archiver 未启用时返回明确错误；
     输出 archived_count/failed_count；str/无效 id 逐条转换与容错
  2. MEMORY_AGENT_SYSTEM_PROMPT 人格重定位——记忆管家/人格守护者定位、
     "遗忘不删除"原则、人格保护说明；移除"7天自动清理"与
     "想删除/清理时用 delete_memory 或 bulk_delete"式引导
  3. data/agents.json 与 prompts_constants.py 单源一致性

不依赖真实 LLM / 后端服务，全部使用 mock 与纯文本断言。

运行：python -m pytest tests/test_memory_humanize_retention.py -v
"""
import json
import os
import re
import sys

import pytest

# 确保 server 包可导入
_CX_SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CX_SERVER not in sys.path:
    sys.path.insert(0, _CX_SERVER)

from server.core.memory.secondary_router import (
    SecondaryInstruction,
    SecondaryModelRouter,
)
from server.core.prompts_constants import MEMORY_AGENT_SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# Mock 依赖（与 test_secondary_router.py 的 mock 模式保持一致）
# --------------------------------------------------------------------------- #
class FakeMemoryManager:
    """内存版 MemoryManager：search_memories 返回可控数据，记录删除调用。

    id 以 str 形式存储（镜像真实 search_memories 返回的 m["id"] 可能是 str 的情况）。
    """

    def __init__(self):
        self.memories = {}
        self._next_id = 1
        self.archiver = None
        self.delete_calls = []

    def add(self, content="内容", importance_score=0.8, **meta):
        mid = self._next_id
        self._next_id += 1
        self.memories[str(mid)] = {
            "id": str(mid),  # 刻意使用 str，验证 int 转换
            "content": content,
            "importance_score": importance_score,
            "metadata": meta,
        }
        return mid

    def add_raw(self, raw_id, importance_score=0.8):
        """注入自定义 id 的记忆（用于无效 id 用例）。"""
        self.memories[str(raw_id)] = {
            "id": raw_id,
            "content": "内容",
            "importance_score": importance_score,
            "metadata": {},
        }

    def search_memories(self, limit=100):
        return list(self.memories.values())[:limit]

    def batch_delete_memories(self, memory_ids, soft_delete=True):
        self.delete_calls.append((list(memory_ids), soft_delete))
        return {"success": len(memory_ids), "failed": 0}


class FakeArchiver:
    """模拟 AdvancedArchiver：记录 archive_memory 调用并返回可控结果。"""

    def __init__(self, fail_ids=(), raise_ids=()):
        self.fail_ids = set(fail_ids)    # 这些 id 返回 None（归档失败）
        self.raise_ids = set(raise_ids)  # 这些 id 抛异常
        self.calls = []

    async def archive_memory(self, memory_id, target_level=1, compress=True):
        self.calls.append({"memory_id": memory_id, "target_level": target_level})
        if memory_id in self.raise_ids:
            raise RuntimeError("归档器内部错误")
        if memory_id in self.fail_ids:
            return None
        return {"memory_id": memory_id, "target_level": target_level}


def _make_router(memory_manager):
    return SecondaryModelRouter(memory_manager=memory_manager)


def _instr(**params):
    return SecondaryInstruction(command="cleanup_memories", parameters=params)


# --------------------------------------------------------------------------- #
# 1. cleanup_memories 归档化
# --------------------------------------------------------------------------- #
class TestCleanupMemoriesArchived:
    def _prepare(self, mm):
        """1 条高分 + 2 条低分，注入可用 FakeArchiver，返回该 archiver。"""
        mm.add("高价值", importance_score=0.9)
        mm.add("低价值1", importance_score=0.01)
        mm.add("低价值2", importance_score=0.05)
        archiver = FakeArchiver()
        mm.archiver = archiver
        return archiver

    @pytest.mark.asyncio
    async def test_low_score_memories_archived_to_level_4(self):
        mm = FakeMemoryManager()
        archiver = self._prepare(mm)
        router = _make_router(mm)

        result = await router.execute_command(_instr(threshold=0.1))

        assert result.status == "success"
        # 仅低分记忆被归档，str id 逐条转换为 int
        assert [c["memory_id"] for c in archiver.calls] == [2, 3]
        assert all(c["target_level"] == 4 for c in archiver.calls)

    @pytest.mark.asyncio
    async def test_no_batch_delete_called(self):
        mm = FakeMemoryManager()
        self._prepare(mm)
        router = _make_router(mm)

        result = await router.execute_command(_instr(threshold=0.1))

        assert result.status == "success"
        # 遗忘≠删除：0 条被删除
        assert mm.delete_calls == []

    @pytest.mark.asyncio
    async def test_output_counts_and_fields(self):
        mm = FakeMemoryManager()
        self._prepare(mm)
        router = _make_router(mm)

        result = await router.execute_command(_instr(threshold=0.1))

        assert result.output["threshold"] == 0.1
        assert result.output["archived_count"] == 2
        assert result.output["failed_count"] == 0
        # 既有 SecondaryResult 字段结构保留
        assert result.execution_time_ms >= 0
        assert result.command == "cleanup_memories"

    @pytest.mark.asyncio
    async def test_invalid_and_failed_ids_counted(self):
        mm = FakeMemoryManager()
        mm.add("高价值", importance_score=0.9)                  # id=1，高分不动
        mm.add_raw("abc", importance_score=0.01)                # 无效 id → failed
        fail_mid = mm.add("归档失败", importance_score=0.02)    # archiver 返回 None
        raise_mid = mm.add("归档异常", importance_score=0.03)   # archiver 抛异常
        archiver = FakeArchiver(fail_ids={fail_mid}, raise_ids={raise_mid})
        mm.archiver = archiver
        router = _make_router(mm)

        result = await router.execute_command(_instr(threshold=0.1))

        assert result.status == "success"
        assert result.output["archived_count"] == 0
        assert result.output["failed_count"] == 3
        # 无效 id 未传给归档器；数字 id 已转 int
        assert [c["memory_id"] for c in archiver.calls] == [fail_mid, raise_mid]

    @pytest.mark.asyncio
    async def test_archiver_disabled_returns_clear_error(self):
        mm = FakeMemoryManager()  # archiver 默认 None（归档未启用）
        mm.add("低价值", importance_score=0.01)
        router = _make_router(mm)

        result = await router.execute_command(_instr(threshold=0.1))

        assert result.status == "error"
        assert "归档功能未启用" in result.output["error"]
        assert "archive_enabled" in result.output["error"]
        # 未启用时同样不得有任何删除行为
        assert mm.delete_calls == []


# --------------------------------------------------------------------------- #
# 2. MEMORY_AGENT_SYSTEM_PROMPT 人格重定位
# --------------------------------------------------------------------------- #
class TestMemoryAgentPromptHumanized:
    def test_positioning_as_memory_butler(self):
        """定位：记忆管家 / 人格守护者——"我记得什么"构成"我是谁"。"""
        assert ("记忆管家" in MEMORY_AGENT_SYSTEM_PROMPT) or (
            "人格守护" in MEMORY_AGENT_SYSTEM_PROMPT
        )
        assert "我记得什么" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "我是谁" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "守护记忆的完整与连贯" in MEMORY_AGENT_SYSTEM_PROMPT

    def test_forgetting_not_deleting_principle(self):
        """核心原则：遗忘不删除——软删除无限期保留、随时可恢复，永不物理清除。"""
        assert "遗忘不删除" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "不会被物理清除" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "随时可恢复" in MEMORY_AGENT_SYSTEM_PROMPT
        # 优先归档/降权/修正，遗忘是最后手段
        assert "遗忘是最后手段" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "归档（archive）" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "降权" in MEMORY_AGENT_SYSTEM_PROMPT

    def test_persona_protection_note(self):
        """人格保护：永久记忆与高情感/高频回忆受保护，遗忘请求被拒绝并建议归档。"""
        assert "人格保护" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "永久记忆" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "高情感" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "高频" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "遗忘请求会被拒绝" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "以归档替代" in MEMORY_AGENT_SYSTEM_PROMPT

    def test_no_auto_cleanup_after_seven_days(self):
        """移除"7天后自动清理"声明（"7天" / "7 天" 双变体均不得出现）。"""
        assert re.search(r"7 ?天", MEMORY_AGENT_SYSTEM_PROMPT) is None

    def test_no_delete_style_guidance(self):
        """不含"想删除/清理时用 delete_memory 或 bulk_delete"式引导。"""
        assert "想删除" not in MEMORY_AGENT_SYSTEM_PROMPT
        assert "清理时用" not in MEMORY_AGENT_SYSTEM_PROMPT
        assert "删除类操作" not in MEMORY_AGENT_SYSTEM_PROMPT

    def test_tool_list_preserved_with_forgetting_semantics(self):
        """9 个工具名称保留，delete_memory/bulk_delete 为遗忘语义。"""
        for tool in [
            "update_memory_node",
            "search_memories",
            "delete_memory",
            "get_memory_stats",
            "search_by_tag",
            "bulk_delete",
            "restore_memory",
            "get_chat_history",
            "get_available_commands",
        ]:
            assert tool in MEMORY_AGENT_SYSTEM_PROMPT
        assert (
            "delete_memory - 遗忘记忆（软删除，可随时恢复，永不物理清除）"
            in MEMORY_AGENT_SYSTEM_PROMPT
        )
        assert (
            "bulk_delete - 批量遗忘记忆（受人格保护的记忆会被跳过）"
            in MEMORY_AGENT_SYSTEM_PROMPT
        )

    def test_confirmation_rules_present(self):
        """执行前确认意图；遗忘类操作需先确认；用中文回答。"""
        assert "执行操作前先确认用户意图" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "遗忘类操作需先与用户确认" in MEMORY_AGENT_SYSTEM_PROMPT
        assert "用中文回答" in MEMORY_AGENT_SYSTEM_PROMPT


# --------------------------------------------------------------------------- #
# 3. agents.json 单源一致性
# --------------------------------------------------------------------------- #
class TestAgentsJsonSync:
    def test_agents_json_memory_prompt_matches_constant(self):
        """agents.json 的 memory-agent system_prompt 与 core 单源常量逐字一致。"""
        from server.api.routers.agents import MEMORY_AGENT_SYSTEM_PROMPT as API_PROMPT

        # api 层 re-export 与 core 单源一致
        assert API_PROMPT == MEMORY_AGENT_SYSTEM_PROMPT

        agents_json = os.path.join(_CX_SERVER, "data", "agents.json")
        with open(agents_json, "r", encoding="utf-8") as fh:
            agents = json.load(fh)
        by_id = {a["id"]: a for a in agents}
        assert by_id["memory-agent"]["system_prompt"] == MEMORY_AGENT_SYSTEM_PROMPT
