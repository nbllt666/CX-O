"""server/autonomy/dream/summarizer.py（SleepAutoSummarizer 入睡首步自动摘要）单测。

覆盖：
1. 有 LLM client：提取会话 + 短程记忆 → LLM 生成摘要 → 写入长期记忆（tags 含 自动摘要/日记）
2. 无 LLM：降级为本地合并摘要，仍写入长期记忆
3. should_summarize：来源为空 → False；指纹与上次一致（已归档）→ False；否则 True
4. 异常隔离：LLM 调用失败 / 持久化失败 / 语料采集失败均不抛出、返回 None 不阻断
5. 无 context_manager 时纯记忆语料仍可摘要；无 memory_manager 时可仅返回摘要不落库
6. parse_msgs 注入解析回调；回退默认角色过滤（排除 system/tool）

运行：python -m pytest tests/test_dream_summarizer.py -q
"""
import asyncio

import pytest

from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.summarizer import SleepAutoSummarizer


# ================================================================ fakes
class FakeLLM:
    """捕获 prompt 并返回固定摘要文本的假 LLM client。"""

    def __init__(self, content="白天在书房写代码，傍晚去公园散步，心情平静。", exc=None):
        self.content = content
        self.exc = exc
        self.prompts = []

    async def chat(self, messages, stream=False, **kw):
        if self.exc:
            raise self.exc
        self.prompts.append(messages)
        return type("Resp", (), {"content": self.content})()


class FakeMemoryManager:
    """记录摘要写入并提供短程记忆查询的假记忆管理器。"""

    def __init__(self, short_term=None):
        self.short_term = list(short_term or [])
        self.written = []

    async def search_memories_async(self, query=None, memory_type=None, limit=10,
                                    offset=0, include_deleted=False, workspace_id="default",
                                    agent_id="default"):
        if memory_type == "short_term":
            return list(self.short_term)
        return []

    async def write_memory_async(self, content, memory_type="long_term", importance=3,
                                 tags=None, metadata=None, permanent=False,
                                 emotion_score=0.0, workspace_id="default", agent_id="default"):
        self.written.append(
            {
                "content": content,
                "memory_type": memory_type,
                "importance": importance,
                "tags": list(tags or []),
                "agent_id": agent_id,
            }
        )
        return len(self.written)


class FakeContextManager:
    """返回一个活跃会话及若干消息的假 ContextManager。"""

    def __init__(self, sessions=None, messages=None):
        self.sessions = sessions or [{"id": "s1"}]
        if messages is None:
            self.messages = [
                {"role": "user", "content": "今天做了一天的梦研究"},
                {"role": "assistant", "content": "很好，我们记录一下"},
                {"role": "system", "content": "不要包含这行"},
            ]
        else:
            self.messages = list(messages)

    def get_sessions(self, workspace_id="default", limit=20, active_only=True):
        return list(self.sessions)

    def get_recent_messages(self, session_id, limit=50):
        return list(self.messages)


def make_summarizer(
    *,
    context_manager=None,
    memory_manager=None,
    llm_client=None,
    parse_msgs=None,
    config=None,
):
    return SleepAutoSummarizer(
        context_manager=context_manager if context_manager is not None else FakeContextManager(),
        memory_manager=memory_manager if memory_manager is not None else FakeMemoryManager(),
        llm_client=llm_client,
        parse_msgs=parse_msgs,
        config=config or DreamConfig(enabled=True),
    )


# ================================================================ ① 有 LLM：生成 + 落库
@pytest.mark.asyncio
class TestLLMSummary:
    async def test_llm_summary_written_to_long_term(self):
        llm = FakeLLM(content="摘要：白天工作，傍晚散步，心情平静。")
        mm = FakeMemoryManager(short_term=[{"content": "短程记忆甲"}])
        s = make_summarizer(memory_manager=mm, llm_client=llm)

        summary = await s.summarize("default")

        assert summary == "摘要：白天工作，傍晚散步，心情平静。"
        # LLM 收到 system+user 两段 prompt
        assert llm.prompts and len(llm.prompts[0]) == 2
        # 写入长期记忆，tags 含 自动摘要/日记
        assert len(mm.written) == 1
        rec = mm.written[0]
        assert rec["memory_type"] == "long_term"
        assert set(rec["tags"]) == {"自动摘要", "日记"}
        assert rec["content"] == summary
        assert rec["agent_id"] == "default"

    async def test_summary_uses_both_session_and_memory_text(self):
        llm = FakeLLM()
        s = make_summarizer(llm_client=llm)
        await s.summarize("default")
        # user prompt 应同时含会话文本与短程记忆内容
        user_texts = [m["content"] for m in llm.prompts[0] if m["role"] == "user"]
        assert any("梦研究" in t for t in user_texts)
        assert any("短程记忆" in t for t in user_texts)

    async def test_parse_msgs_callback_used(self):
        llm = FakeLLM()

        def _parse(msgs):
            return ["[解析]" + m["content"] for m in msgs if m["role"] == "user"]

        s = SleepAutoSummarizer(
            context_manager=FakeContextManager(),
            memory_manager=FakeMemoryManager(),
            llm_client=llm,
            parse_msgs=_parse,
        )
        await s.summarize("default")
        user_texts = [m["content"] for m in llm.prompts[0] if m["role"] == "user"]
        assert any("[解析]" in t for t in user_texts)


# ================================================================ ② 无 LLM：本地降级仍入库
@pytest.mark.asyncio
class TestLocalDegrade:
    async def test_no_llm_uses_local_merge_and_still_persists(self):
        mm = FakeMemoryManager()
        s = make_summarizer(memory_manager=mm, llm_client=None)
        summary = await s.summarize("default")
        assert summary  # 有内容
        assert "梦研究" in summary
        assert len(mm.written) == 1  # 仍落库
        assert mm.written[0]["memory_type"] == "long_term"


# ================================================================ ③ should_summarize
class TestShouldSummarize:
    def test_empty_source_false(self):
        s = make_summarizer(llm_client=None)
        assert s.should_summarize("") is False
        assert s.should_summarize("   ") is False

    def test_new_source_true(self):
        s = make_summarizer(llm_client=None)
        assert s.should_summarize("今天的工作记录") is True

    def test_same_fingerprint_false_after_archive(self):
        s = make_summarizer(llm_client=None)
        assert s.should_summarize("同一段内容") is True
        s._last_fingerprint = s._fingerprint("同一段内容")  # 模拟已归档
        assert s.should_summarize("同一段内容") is False
        # 不同内容 → 需要再次摘要
        assert s.should_summarize("别的内容") is True

    @pytest.mark.asyncio
    async def test_summarize_skips_when_empty_source(self):
        s = SleepAutoSummarizer(
            context_manager=FakeContextManager(
                sessions=[{"id": "s1"}], messages=[]
            ),
            memory_manager=FakeMemoryManager(short_term=[]),
            llm_client=FakeLLM(),
        )
        result = await s.summarize("default")
        assert result is None  # 来源为空 → 跳过


# ================================================================ ④ 异常隔离
@pytest.mark.asyncio
class TestExceptionIsolation:
    async def test_llm_exception_degrades_and_does_not_raise(self):
        llm = FakeLLM(exc=RuntimeError("llm down"))
        mm = FakeMemoryManager()
        # llm 调用异常 → 降级本地摘要，仍返回文本且不抛出
        s = make_summarizer(memory_manager=mm, llm_client=llm)
        summary = await s.summarize("default")
        assert summary  # 本地降级摘要
        assert len(mm.written) == 1  # 仍落库

    async def test_memory_persist_exception_isolated(self):
        class _BadMM(FakeMemoryManager):
            async def write_memory_async(self, **kw):
                raise RuntimeError("db down")

        llm = FakeLLM()
        s = make_summarizer(memory_manager=_BadMM(), llm_client=llm)
        result = await s.summarize("default")
        # 持久化失败被隔离，摘要文本仍返回、不抛出
        assert result == llm.content

    async def test_context_collect_exception_isolated(self):
        class _BadCM(FakeContextManager):
            def get_recent_messages(self, session_id, limit=50):
                raise RuntimeError("session down")

        llm = FakeLLM()
        mm = FakeMemoryManager(short_term=[{"content": "只剩记忆语料"}])
        s = SleepAutoSummarizer(
            context_manager=_BadCM(), memory_manager=mm, llm_client=llm
        )
        summary = await s.summarize("default")
        # 会话语料抛异常 → 隔离，仍用记忆语料摘要
        assert summary == llm.content
        user_texts = [m["content"] for m in llm.prompts[0] if m["role"] == "user"]
        assert any("只剩记忆语料" in t for t in user_texts)

    async def test_no_memory_manager_returns_summary_without_persist(self):
        llm = FakeLLM()
        s = SleepAutoSummarizer(
            context_manager=FakeContextManager(), memory_manager=None, llm_client=llm
        )
        result = await s.summarize("default")
        assert result == llm.content  # 返回摘要但不落库（无 memory_manager）


# ================================================================ ⑤ 记忆-only
@pytest.mark.asyncio
class TestMemoryOnlySource:
    async def test_memory_only_no_context_manager(self):
        llm = FakeLLM(content="纯记忆摘要")
        mm = FakeMemoryManager(short_term=[{"content": "记忆一"}, {"content": "记忆二"}])
        s = SleepAutoSummarizer(
            context_manager=None, memory_manager=mm, llm_client=llm
        )
        result = await s.summarize("default")
        assert result == "纯记忆摘要"
        assert len(mm.written) == 1