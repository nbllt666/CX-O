"""CX-O-Autonomy P1-T7 反思层单测（mock llm_client 与 memory_actions）。

覆盖：
① DiaryGenerator.generate_diary 正常路径（mock content 返回文本，断言
   write_memory 以 permanent=True / importance=5 / tags=["#日记","#经历"] 调用，
   返回 diary 与 memory_id）
② generate_diary LLM 失败返回 {"diary": "", "memory_id": None, "error": ...}
   不冒泡（含 client 抛异常、LLMResponse.error、记忆写入失败三个子场景）
③ Consolidator 无 provider 返回 {"consolidated": N, "distilled": False}
④ Consolidator 有 provider 返回 provider 结果（含同步/异步 provider）
⑤ FeedbackEvaluator 成功行动得分>0.5、失败行动低分、无 provider 时
   submitted False（含 provider + success 提交偏好信号的扩展场景）

运行：python -m pytest tests/test_autonomy_reflection.py -q
"""
import pytest

from server.autonomy.reflection import Consolidator, DiaryGenerator, FeedbackEvaluator
from server.core.llm.client import LLMResponse


class FakeLLMClient:
    """LLMClient 替身：按顺序返回预设响应，最后一个响应复用作为兜底。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.chat_calls = []

    async def chat(self, messages, stream=False, **kwargs):
        self.chat_calls.append({"messages": messages, "stream": stream, "kwargs": kwargs})
        if len(self.responses) <= 1:
            return self.responses[0]
        return self.responses.pop(0)


class RaisingLLMClient:
    """每次 chat 都抛异常的客户端，用于验证 LLM 失败不冒泡。"""

    async def chat(self, messages, stream=False, **kwargs):
        raise RuntimeError("mock llm down")


class FakeMemoryActions:
    """MemoryActions 替身：记录 write_memory 调用参数，可注入返回结果或异常。"""

    def __init__(self, memory_id="mem-1", write_error=None):
        self.memory_id = memory_id
        self.write_error = write_error
        self.write_kwargs = None

    async def write_memory(self, **kwargs):
        self.write_kwargs = kwargs
        if self.write_error is not None:
            raise self.write_error
        return self.memory_id


def make_daily_log():
    """构造当日活动日志（对齐 AuditStore.list 的 items 字段）。"""
    return [
        {
            "timestamp": "2026-08-22T10:00:00+08:00",
            "action": "read_news",
            "target": "AI 新闻",
            "result": "success",
            "trigger_reason": "好奇心较高",
        },
        {
            "timestamp": "2026-08-22T15:00:00+08:00",
            "action": "write_memory",
            "target": "记忆整理",
            "result": "success",
            "trigger_reason": "素材沉淀",
        },
    ]


# ================================================================ ① generate_diary 正常路径
class TestGenerateDiaryNormal:
    @pytest.mark.asyncio
    async def test_generates_diary_and_writes_memory(self):
        content = "今天的我读了很多新闻，又整理了记忆，觉得收获满满。"
        client = FakeLLMClient([LLMResponse(content=content, finish_reason="stop")])
        memory = FakeMemoryActions(memory_id="mem-42")
        gen = DiaryGenerator(
            llm_client=client,
            memory_actions=memory,
            persona={"system_prompt": "你是一个温柔细腻的少女。"},
        )
        result = await gen.generate_diary(make_daily_log(), date="2026-08-22")

        # 返回 diary 与 memory_id
        assert result["diary"] == content
        assert result["memory_id"] == "mem-42"
        assert "error" not in result

        # 断言 write_memory 以 permanent=True / importance=5 / tags 调用
        assert memory.write_kwargs["permanent"] is True
        assert memory.write_kwargs["importance"] == 5
        assert memory.write_kwargs["tags"] == ["#日记", "#经历"]
        assert memory.write_kwargs["type"] == "long_term"
        assert memory.write_kwargs["content"] == content

        # 断言提示词组装：system 含人设与第一人称日记指令；user 含日期与活动日志
        messages = client.chat_calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert "温柔细腻" in messages[0]["content"]
        assert "第一人称" in messages[0]["content"]
        assert "200字以内" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert "2026-08-22" in messages[1]["content"]
        assert "read_news" in messages[1]["content"]

    @pytest.mark.asyncio
    async def test_default_date_and_empty_persona(self):
        client = FakeLLMClient([LLMResponse(content="今天无事发生。", finish_reason="stop")])
        memory = FakeMemoryActions()
        gen = DiaryGenerator(llm_client=client, memory_actions=memory)  # 无 persona
        result = await gen.generate_diary([])  # 空日志、无日期

        assert result["diary"] == "今天无事发生。"
        assert result["memory_id"] == "mem-1"
        messages = client.chat_calls[0]["messages"]
        assert "【人设】" not in messages[0]["content"]
        assert "今天" in messages[1]["content"]


# ================================================================ ② generate_diary LLM 失败不冒泡
class TestGenerateDiaryLLMFailure:
    @pytest.mark.asyncio
    async def test_client_exception_returns_error_dict(self):
        gen = DiaryGenerator(llm_client=RaisingLLMClient(), memory_actions=FakeMemoryActions())
        result = await gen.generate_diary(make_daily_log())

        assert result["diary"] == ""
        assert result["memory_id"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_response_error_returns_error_dict(self):
        client = FakeLLMClient(
            [LLMResponse(content="", finish_reason="error", error="HTTP 500")]
        )
        gen = DiaryGenerator(llm_client=client, memory_actions=FakeMemoryActions())
        result = await gen.generate_diary(make_daily_log())

        assert result["diary"] == ""
        assert result["memory_id"] is None
        assert "error" in result

    @pytest.mark.asyncio
    async def test_memory_write_failure_keeps_diary(self):
        content = "日记文本仍然生成成功。"
        client = FakeLLMClient([LLMResponse(content=content, finish_reason="stop")])
        memory = FakeMemoryActions(write_error=RuntimeError("记忆库不可用"))
        gen = DiaryGenerator(llm_client=client, memory_actions=memory)
        result = await gen.generate_diary(make_daily_log())

        # LLM 已产出日记；仅记忆写入失败 → diary 保留、memory_id 为 None、带 error
        assert result["diary"] == content
        assert result["memory_id"] is None
        assert "error" in result


# ================================================================ ③ Consolidator 无 provider
class TestConsolidatorNoProvider:
    @pytest.mark.asyncio
    async def test_returns_distilled_false(self):
        c = Consolidator()
        result = await c.consolidate([{"a": 1}, {"b": 2}, {"c": 3}])

        assert result == {"consolidated": 3, "distilled": False}


# ================================================================ ④ Consolidator 有 provider
class TestConsolidatorWithProvider:
    @pytest.mark.asyncio
    async def test_returns_provider_result(self):
        def provider(entries):
            return {"consolidated": len(entries), "distilled": True, "summary": "ok"}

        c = Consolidator(distillation_provider=provider)
        result = await c.consolidate([{"a": 1}])

        assert result == {"consolidated": 1, "distilled": True, "summary": "ok"}

    @pytest.mark.asyncio
    async def test_awaits_async_provider(self):
        async def provider(entries):
            return {"distilled": True, "count": len(entries)}

        c = Consolidator(distillation_provider=provider)
        result = await c.consolidate([{"a": 1}, {"b": 2}])

        assert result == {"distilled": True, "count": 2}


# ================================================================ ⑤ FeedbackEvaluator
class TestFeedbackEvaluator:
    @pytest.mark.asyncio
    async def test_success_high_score_positive(self):
        ev = FeedbackEvaluator()
        result = await ev.evaluate({"action": "write_memory", "result": "success"})

        assert result["action"] == "write_memory"
        assert result["result"] == "success"
        assert result["score"] > 0.5
        assert result["signal"] == "positive"

    @pytest.mark.asyncio
    async def test_failure_low_score_negative(self):
        ev = FeedbackEvaluator()
        result = await ev.evaluate({"action": "search", "result": "failed"})

        assert result["score"] < 0.5
        assert result["signal"] == "negative"

    @pytest.mark.asyncio
    async def test_submitted_false_without_provider(self):
        ev = FeedbackEvaluator()  # 无 tuner_provider
        for r in ("success", "failed", "blocked", "skipped"):
            result = await ev.evaluate({"action": "x", "result": r})
            assert result["submitted"] is False

    @pytest.mark.asyncio
    async def test_provider_called_only_on_success(self):
        submitted = []

        def provider(signal, action_result):
            submitted.append((signal, action_result))

        ev = FeedbackEvaluator(tuner_provider=provider)

        # 成功 → 提交偏好信号，submitted True
        ok = await ev.evaluate({"action": "write_memory", "result": "success"})
        assert ok["submitted"] is True
        assert len(submitted) == 1
        assert submitted[0][0] == "positive"

        # 失败 → 不提交，submitted False
        fail = await ev.evaluate({"action": "search", "result": "failed"})
        assert fail["submitted"] is False
        assert len(submitted) == 1

    @pytest.mark.asyncio
    async def test_provider_exception_does_not_bubble(self):
        def provider(signal, action_result):
            raise RuntimeError("tuner down")

        ev = FeedbackEvaluator(tuner_provider=provider)
        result = await ev.evaluate({"action": "write_memory", "result": "success"})

        assert result["submitted"] is False
        assert result["score"] > 0.5
