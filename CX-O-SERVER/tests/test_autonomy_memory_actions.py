"""CX-O-Autonomy P1-T4 记忆读写行动单测（mock memory_manager）。

覆盖：
① write_memory 传参正确（content/tags/type/permanent/importance/metadata/agent_id/workspace_id 逐项断言）
② write_memory 空内容抛 ValueError
③ write_memory 底层异常被捕获，返回 {'error': ...} 错误结构
④ retrieve_memory 传参（query/limit/tags）正确并返回列表（含 type 归一化字段）
⑤ memory_manager 未注入时优雅降级（write 返回错误结构 / retrieve 返回 []）

运行：python -m pytest tests/test_autonomy_memory_actions.py -q
"""
import pytest

from server.autonomy.action.content.memory_actions import MemoryActions


class FakeMemoryManager:
    """memory manager 替身：记录调用参数，可注入返回结果或异常。"""

    def __init__(self, memory_id=42, memories=None, write_error=None, search_error=None):
        self.memory_id = memory_id
        self.memories = memories if memories is not None else []
        self.write_error = write_error
        self.search_error = search_error
        self.write_kwargs = None
        self.search_kwargs = None

    async def write_memory_async(self, **kwargs):
        self.write_kwargs = kwargs
        if self.write_error is not None:
            raise self.write_error
        return self.memory_id

    async def search_memories_async(self, **kwargs):
        self.search_kwargs = kwargs
        if self.search_error is not None:
            raise self.search_error
        return self.memories


# ================================================================ ① write_memory 传参正确
class TestWriteMemoryArgs:
    @pytest.mark.asyncio
    async def test_passes_all_args_and_returns_str_memory_id(self):
        mgr = FakeMemoryManager(memory_id=7)
        actions = MemoryActions(memory_manager=mgr, agent_id="测试agent")
        result = await actions.write_memory(
            content="今天研究了三层契约",
            tags=["architecture", "contract"],
            type="long_term",
            permanent=True,
            importance=5,
            metadata={"source": "autonomy"},
        )
        assert result == "7"
        assert mgr.write_kwargs == {
            "content": "今天研究了三层契约",
            "memory_type": "long_term",
            "importance": 5,
            "tags": ["architecture", "contract"],
            "metadata": {"source": "autonomy"},
            "permanent": True,
            "workspace_id": "default",
            "agent_id": "测试agent",
        }

    @pytest.mark.asyncio
    async def test_defaults_agent_workspace_type(self):
        mgr = FakeMemoryManager()
        actions = MemoryActions(memory_manager=mgr)  # 未指定 agent_id → 默认 "default"
        result = await actions.write_memory(content="默认agent写入")
        assert result == "42"
        assert mgr.write_kwargs["agent_id"] == "default"
        assert mgr.write_kwargs["workspace_id"] == "default"
        assert mgr.write_kwargs["memory_type"] == "long_term"
        assert mgr.write_kwargs["permanent"] is False
        assert mgr.write_kwargs["importance"] == 3
        assert mgr.write_kwargs["tags"] == []
        assert mgr.write_kwargs["metadata"] == {}


# ================================================================ ② write_memory 空内容抛 ValueError
class TestWriteMemoryEmptyContent:
    @pytest.mark.asyncio
    async def test_empty_content_raises_valueerror(self):
        actions = MemoryActions(memory_manager=FakeMemoryManager())
        for bad in ("", "   ", "\n\t"):
            with pytest.raises(ValueError):
                await actions.write_memory(content=bad)


# ================================================================ ③ write_memory 底层异常 → 错误结构
class TestWriteMemoryError:
    @pytest.mark.asyncio
    async def test_exception_returns_error_structure(self):
        mgr = FakeMemoryManager(write_error=RuntimeError("数据库不可用"))
        actions = MemoryActions(memory_manager=mgr)
        result = await actions.write_memory(content="会失败的记忆")
        assert isinstance(result, dict)
        assert "error" in result
        assert result["memory_id"] is None


# ================================================================ ④ retrieve_memory 传参与返回
class TestRetrieveMemory:
    @pytest.mark.asyncio
    async def test_passes_args_and_returns_normalized_list(self):
        raw = [
            {
                "id": 1, "content": "记忆A", "memory_type": "long_term",
                "tags": ["t1"], "importance": 4, "created_at": "2026-08-22T00:00:00",
            },
            {
                "id": 2, "content": "记忆B", "memory_type": "short_term",
                "tags": [], "importance": 3, "created_at": "2026-08-21T00:00:00",
            },
        ]
        mgr = FakeMemoryManager(memories=raw)
        actions = MemoryActions(memory_manager=mgr)
        result = await actions.retrieve_memory(query="记忆", limit=3, tags=["t1"])
        assert mgr.search_kwargs == {
            "query": "记忆",
            "tags": ["t1"],
            "limit": 3,
            "workspace_id": "default",
            "agent_id": "default",
        }
        assert isinstance(result, list)
        assert len(result) == 2
        # 归一化：底层 memory_type → 对外补充 type
        assert result[0]["type"] == "long_term"
        assert result[1]["type"] == "short_term"
        assert result[0]["content"] == "记忆A"
        assert result[0]["importance"] == 4
        assert result[0]["created_at"] == "2026-08-22T00:00:00"
        assert result[0]["tags"] == ["t1"]
        # 原始字段保留
        assert result[0]["memory_type"] == "long_term"

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self):
        mgr = FakeMemoryManager(search_error=RuntimeError("检索失败"))
        actions = MemoryActions(memory_manager=mgr)
        result = await actions.retrieve_memory(query="任意")
        assert result == []


# ================================================================ ⑤ memory_manager 未注入 → 优雅降级
class TestNoManagerGracefulDegrade:
    @pytest.mark.asyncio
    async def test_write_returns_error_structure(self):
        actions = MemoryActions()  # 未注入 memory manager
        result = await actions.write_memory(content="测试")
        assert isinstance(result, dict)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_list(self):
        actions = MemoryActions()  # 未注入 memory manager
        result = await actions.retrieve_memory(query="测试")
        assert result == []
