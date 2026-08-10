"""server.core.memory.secondary_router (SecondaryModelRouter) 单元测试。

覆盖指令权限校验、命令分发、记忆摘要/归档/清理/重要性分析/衰减/洞察/批量处理、
对话摘要/关键点提取/报告生成、自定义命令等核心逻辑。
使用内存 Mock 依赖，不依赖真实 LLM / 数据库 / 网络。

运行：python -m pytest tests/test_secondary_router.py -v
"""
import pytest

from server.core.memory.secondary_router import (
    SecondaryCommand,
    SecondaryInstruction,
    SecondaryModelRouter,
)


class FakeMemoryManager:
    """内存版 MemoryManager，记录调用并返回可控数据。"""

    def __init__(self):
        self.memories = {}
        self._next_id = 1
        self.calls = {"update": [], "delete": [], "write": []}

    def add(self, content="内容", importance_score=0.8, importance=3, **meta):
        mid = self._next_id
        self._next_id += 1
        self.memories[mid] = {
            "id": mid,
            "content": content,
            "importance_score": importance_score,
            "importance": importance,
            "metadata": meta,
        }
        return mid

    def get_memory(self, memory_id):
        return self.memories.get(memory_id)

    async def update_memory_async(self, memory_id, new_metadata=None):
        self.calls["update"].append((memory_id, new_metadata))
        if memory_id not in self.memories:
            return False
        self.memories[memory_id].setdefault("metadata", {}).update(new_metadata or {})
        return True

    async def write_memory_async(self, content, memory_type, importance, tags, metadata=None):
        self.calls["write"].append(
            (content, memory_type, importance, tags, metadata)
        )
        mid = self._next_id
        self._next_id += 1
        self.memories[mid] = {
            "id": mid,
            "content": content,
            "importance_score": importance,
            "importance": importance,
            "memory_type": memory_type,
            "tags": tags,
            "metadata": metadata or {},
        }
        return mid

    def search_memories(self, limit=100):
        return [self.memories[k] for k in sorted(self.memories)]

    def batch_delete_memories(self, memory_ids, soft_delete=True):
        self.calls["delete"].append((list(memory_ids), soft_delete))
        return {"success": len(memory_ids), "failed": 0}

    def get_decay_statistics(self):
        return {
            "avg_time_score": 0.5,
            "avg_importance_score": 0.6,
            "importance_distribution": {"high": 2, "low": 1},
            "reactivation_stats": {"reactivated": 1},
        }

    def get_statistics(self):
        return {"total": len(self.memories), "by_type": {"conversation_summary": 0}}

    def sync_decay_values(self):
        return {"updated": 3, "failed": 0, "total": 3}


class FakeResponse:
    """模拟 LLM 客户端返回对象。"""

    def __init__(self, content):
        self.content = content


class FakeLLMClient:
    """可配置返回内容的模拟 LLM 客户端。"""

    def __init__(self, response_content=""):
        self.response_content = response_content
        self.calls = []

    async def chat(self, messages, stream=False, **kwargs):
        self.calls.append({"messages": messages, "stream": stream, "kwargs": kwargs})
        return FakeResponse(self.response_content)


class FakeModelRouter:
    def __init__(self, summary_client=None, memory_client=None):
        self._summary = summary_client
        self._memory = memory_client

    def get_client(self, model_type):
        if model_type == "summary":
            return self._summary
        if model_type == "memory":
            return self._memory
        return None


class FakeContextManager:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.updated = []

    def get_messages(self, conversation_id, limit=100):
        return self.messages

    def update_session(self, conversation_id, summary=None):
        self.updated.append((conversation_id, summary))
        return True


@pytest.fixture
def router():
    """默认路由器：全部依赖为 None，便于逐用例注入。"""
    return SecondaryModelRouter(memory_manager=FakeMemoryManager())


def _instr(command, **params):
    return SecondaryInstruction(command=command, parameters=params)


# ---------------------------------------------------------------- 权限校验
class TestPermission:
    def test_main_always_allowed(self, router):
        """主模型可执行任意命令。"""
        for cmd in SecondaryCommand.__members__.values():
            assert router.validate_permission(cmd.value, is_from_main=True) is True

    def test_secondary_blocked_on_prohibited(self, router):
        """副模型无权执行 PROHIBITED_COMMANDS。"""
        for cmd in [
            "add_permanent_memory",
            "delete_permanent_memory",
            "update_permanent_memory",
            "get_permanent_memories",
        ]:
            assert router.validate_permission(cmd, is_from_main=False) is False

    def test_secondary_allowed_on_normal_command(self, router):
        """副模型可执行未被禁止的命令。"""
        assert (
            router.validate_permission("summarize_memory", is_from_main=False) is True
        )

    @pytest.mark.asyncio
    async def test_execute_blocked_returns_error(self, router):
        """副模型执行禁止命令返回 Permission denied。"""
        result = await router.execute_command(
            _instr("add_permanent_memory"), is_from_main=False
        )
        assert result.status == "error"
        assert result.output["error"] == "Permission denied"
        assert result.suggestions == ["请使用主模型执行此操作"]


# ---------------------------------------------------------------- 命令分发
class TestDispatch:
    @pytest.mark.asyncio
    async def test_unknown_command(self, router):
        result = await router.execute_command(_instr("no_such_command"))
        assert result.status == "error"
        assert "Unknown command" in result.output["error"]

    @pytest.mark.asyncio
    async def test_execute_records_history(self, router):
        router.memory_manager.add("内容")
        await router.execute_command(_instr("summarize_memory", memory_id=1))
        history = router.get_execution_history()
        assert len(history) == 1
        assert history[0]["command"] == "summarize_memory"
        assert history[0]["status"] == "success"
        assert history[0]["execution_time_ms"] >= 0

    @pytest.mark.asyncio
    async def test_execute_runs_command_impl(self, router):
        router.memory_manager.add("需要摘要的内容")
        result = await router.execute_command(_instr("summarize_memory", memory_id=1))
        assert result.status == "success"
        assert result.command == "summarize_memory"


# ---------------------------------------------------------------- summarize_memory
class TestSummarizeMemory:
    @pytest.mark.asyncio
    async def test_memory_not_found(self, router):
        result = await router.execute_command(_instr("summarize_memory", memory_id=999))
        assert result.status == "error"
        assert result.output["error"] == "Memory not found"

    @pytest.mark.asyncio
    async def test_empty_content(self, router):
        router.memory_manager.add("")
        result = await router.execute_command(_instr("summarize_memory", memory_id=1))
        assert result.status == "error"
        assert result.output["error"] == "Memory content is empty"

    @pytest.mark.asyncio
    async def test_with_llm_client(self, router):
        router.memory_manager.add("这是一段很长的原始记忆内容。" * 10)
        client = FakeLLMClient(response_content="浓缩后的摘要")
        router.set_llm_client(client)
        result = await router.execute_command(
            _instr("summarize_memory", memory_id=1, max_length=50)
        )
        assert result.status == "success"
        assert result.output["summary"] == "浓缩后的摘要"
        assert result.output["original_length"] > 0
        # 摘要已写回记忆
        assert router.memory_manager.memories[1]["metadata"]["summary"] == "浓缩后的摘要"

    @pytest.mark.asyncio
    async def test_without_client_truncates(self, router):
        router.memory_manager.add("原始内容" * 200)
        result = await router.execute_command(
            _instr("summarize_memory", memory_id=1, max_length=10)
        )
        assert result.status == "success"
        assert result.output["summary"].endswith("...")


# ---------------------------------------------------------------- archive_memory
class TestArchiveMemory:
    @pytest.mark.asyncio
    async def test_archive_success(self, router):
        router.memory_manager.add("内容")
        result = await router.execute_command(
            _instr("archive_memory", memory_id=1, reason="已过时")
        )
        assert result.status == "success"
        assert result.output["archived"] is True
        meta = router.memory_manager.memories[1]["metadata"]
        assert meta["archived"] is True
        assert meta["archive_reason"] == "已过时"

    @pytest.mark.asyncio
    async def test_archive_failure(self, router):
        result = await router.execute_command(_instr("archive_memory", memory_id=999))
        assert result.status == "error"
        assert result.output["error"] == "Failed to archive memory"


# ---------------------------------------------------------------- cleanup_memories
class TestCleanupMemories:
    @pytest.mark.asyncio
    async def test_filters_low_importance(self, router):
        router.memory_manager.add("高价值", importance_score=0.9)
        router.memory_manager.add("低价值", importance_score=0.01)
        result = await router.execute_command(
            _instr("cleanup_memories", threshold=0.1)
        )
        assert result.status == "success"
        # 仅低价值记忆被删除
        deleted_ids = router.memory_manager.calls["delete"]
        assert deleted_ids and deleted_ids[0][0] == [2]


# ---------------------------------------------------------------- analyze_importance
class TestAnalyzeImportance:
    @pytest.mark.asyncio
    async def test_memory_not_found(self, router):
        result = await router.execute_command(_instr("analyze_importance", memory_id=999))
        assert result.status == "error"
        assert result.output["error"] == "Memory not found"

    @pytest.mark.asyncio
    async def test_with_client_parses_json(self, router):
        router.memory_manager.add("用户反复提及的重要信息")
        client = FakeLLMClient(
            response_content='{"score": 5, "reason": "非常关键", "suggested_tags": ["重要"]}'
        )
        router.set_llm_client(client)
        result = await router.execute_command(
            _instr("analyze_importance", memory_id=1, context="多次")
        )
        assert result.status == "success"
        assert result.output["suggested_level"] == 5
        assert result.output["suggested_tags"] == ["重要"]

    @pytest.mark.asyncio
    async def test_without_client_keeps_current(self, router):
        router.memory_manager.add("内容", importance=3)
        result = await router.execute_command(_instr("analyze_importance", memory_id=1))
        assert result.status == "success"
        assert result.output["suggested_level"] == 3
        assert result.output["reason"] == "无可用模型"


# ---------------------------------------------------------------- decay_memories
class TestDecayMemories:
    @pytest.mark.asyncio
    async def test_dry_run_preview(self, router):
        result = await router.execute_command(_instr("decay_memories", dry_run=True))
        assert result.status == "success"
        assert result.output["dry_run"] is True
        assert "statistics" in result.output

    @pytest.mark.asyncio
    async def test_actual_execution(self, router):
        result = await router.execute_command(_instr("decay_memories", dry_run=False))
        assert result.status == "success"
        assert result.output["dry_run"] is False
        assert result.output["updated"] == 3


# ---------------------------------------------------------------- get_memory_insights
class TestGetMemoryInsights:
    @pytest.mark.asyncio
    async def test_basic(self, router):
        result = await router.execute_command(
            _instr("get_memory_insights", time_range="30d")
        )
        assert result.status == "success"
        assert result.output["basic_statistics"]["total"] == 0

    @pytest.mark.asyncio
    async def test_with_metrics(self, router):
        result = await router.execute_command(
            _instr(
                "get_memory_insights",
                metrics=["importance_distribution", "reactivation_stats"],
            )
        )
        assert result.status == "success"
        assert "importance_distribution" in result.output
        assert "reactivation_stats" in result.output


# ---------------------------------------------------------------- batch_process
class TestBatchProcess:
    @pytest.mark.asyncio
    async def test_delete_action(self, router):
        router.memory_manager.add("A")
        router.memory_manager.add("B")
        result = await router.execute_command(
            _instr("batch_process", action="delete", memory_ids=[1, 2])
        )
        assert result.status == "success"
        assert result.output["deleted_count"] == 2

    @pytest.mark.asyncio
    async def test_summarize_action(self, router):
        for _ in range(2):
            router.memory_manager.add("需要摘要的内容" * 20)
        result = await router.execute_command(
            _instr("batch_process", action="summarize", memory_ids=[1, 2])
        )
        assert result.status == "success"
        assert result.output["summarized_count"] == 2

    @pytest.mark.asyncio
    async def test_unsupported_action(self, router):
        result = await router.execute_command(
            _instr("batch_process", action="purge", memory_ids=[1])
        )
        assert result.status == "error"
        assert "Unsupported action" in result.output["error"]


# ---------------------------------------------------------------- summarize_conversation
class TestSummarizeConversation:
    @pytest.mark.asyncio
    async def test_no_context_manager(self, router):
        result = await router.execute_command(
            _instr("summarize_conversation", conversation_id="s1")
        )
        assert result.status == "error"
        assert result.output["error"] == "Context manager not available"

    @pytest.mark.asyncio
    async def test_empty_conversation(self, router):
        router.context_manager = FakeContextManager(messages=[])
        result = await router.execute_command(
            _instr("summarize_conversation", conversation_id="s1")
        )
        assert result.status == "error"
        assert result.output["error"] == "Conversation not found or empty"

    @pytest.mark.asyncio
    async def test_no_summary_client(self, router):
        router.context_manager = FakeContextManager(messages=[{"role": "user", "content": "hi"}])
        result = await router.execute_command(
            _instr("summarize_conversation", conversation_id="s1")
        )
        assert result.status == "error"
        assert result.output["error"] == "Summary model not available"

    @pytest.mark.asyncio
    async def test_success_saves_memory(self, router):
        router.context_manager = FakeContextManager(
            messages=[{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好呀"}]
        )
        client = FakeLLMClient(
            response_content='{"key_points": [{"content": "要点1", "importance": "high", '
            '"participants": ["user"]}], "report": {"topic": "寒暄", "participants": '
            '["user", "assistant"], "message_count": 2, "main_discussion": "打招呼", '
            '"sentiment": "positive"}}'
        )
        router.set_llm_client(client)
        result = await router.execute_command(
            _instr("summarize_conversation", conversation_id="s1", save_as_memory=True)
        )
        assert result.status == "success"
        assert result.output["key_points"][0]["content"] == "要点1"
        assert result.output["summary_memory_id"] is not None
        # 会话摘要已更新
        assert router.context_manager.updated

    @pytest.mark.asyncio
    async def test_skip_save_as_memory(self, router):
        router.context_manager = FakeContextManager(messages=[{"role": "user", "content": "hi"}])
        client = FakeLLMClient(
            response_content='{"key_points": [], "report": {"topic": "寒暄"}}'
        )
        router.set_llm_client(client)
        result = await router.execute_command(
            _instr("summarize_conversation", conversation_id="s1", save_as_memory=False)
        )
        assert result.status == "success"
        assert result.output["summary_memory_id"] is None


# ---------------------------------------------------------------- extract_key_points
class TestExtractKeyPoints:
    @pytest.mark.asyncio
    async def test_empty_text(self, router):
        result = await router.execute_command(_instr("extract_key_points", text=""))
        assert result.status == "error"
        assert result.output["error"] == "Text is empty"

    @pytest.mark.asyncio
    async def test_with_client(self, router):
        client = FakeLLMClient(response_content='["要点1", "要点2"]')
        router.set_llm_client(client)
        result = await router.execute_command(
            _instr("extract_key_points", text="用户提出了多个需求", max_points=3)
        )
        assert result.status == "success"
        assert result.output["key_points"] == ["要点1", "要点2"]

    @pytest.mark.asyncio
    async def test_without_client_fallback(self, router):
        result = await router.execute_command(
            _instr("extract_key_points", text="第一句。第二句。第三句。", max_points=2)
        )
        assert result.status == "success"
        assert result.output["key_points"] == ["第一句", "第二句"]


# ---------------------------------------------------------------- generate_memory_report
class TestGenerateMemoryReport:
    @pytest.mark.asyncio
    async def test_summary_report(self, router):
        result = await router.execute_command(
            _instr("generate_memory_report", report_type="summary")
        )
        assert result.status == "success"
        assert result.output["report_type"] == "summary"
        assert "statistics" in result.output

    @pytest.mark.asyncio
    async def test_detailed_report_with_analysis(self, router):
        client = FakeLLMClient(
            response_content='{"interpretation": "健康", "trends": ["上升"], '
            '"suggestions": ["清理"]}'
        )
        router.set_llm_client(client)
        result = await router.execute_command(
            _instr("generate_memory_report", report_type="detailed")
        )
        assert result.status == "success"
        assert result.output["analysis"]["interpretation"] == "健康"


# ---------------------------------------------------------------- custom_command
class TestCustomCommand:
    @pytest.mark.asyncio
    async def test_missing_user_message(self, router):
        result = await router.execute_command(_instr("custom"))
        assert result.status == "error"
        assert result.output["error"] == "user_message is required"

    @pytest.mark.asyncio
    async def test_no_memory_client(self, router):
        result = await router.execute_command(_instr("custom", user_message="整理记忆"))
        assert result.status == "error"
        assert result.output["error"] == "Memory model not available"

    @pytest.mark.asyncio
    async def test_success(self, router):
        client = FakeLLMClient(response_content="已整理完成")
        router.set_model_router(FakeModelRouter(memory_client=client))
        result = await router.execute_command(_instr("custom", user_message="整理记忆"))
        assert result.status == "success"
        assert result.output["response"] == "已整理完成"
        # 系统提示词已注入
        assert client.calls[0]["messages"][0]["role"] == "system"


# ---------------------------------------------------------------- 摘要客户端选择
class TestSummaryClientSelection:
    def test_prefers_router_summary(self, router):
        router_client = FakeLLMClient()
        router.set_model_router(FakeModelRouter(summary_client=router_client))
        assert router._get_summary_client() is router_client

    def test_falls_back_to_llm_client(self, router):
        llm = FakeLLMClient()
        router.set_llm_client(llm)
        assert router._get_summary_client() is llm

    def test_none_when_unavailable(self, router):
        assert router._get_summary_client() is None