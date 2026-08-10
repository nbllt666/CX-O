"""server.core.context.summarizer 单元测试。

覆盖 ContextSummarizer：空消息、规则摘要（concise/detailed 风格、关键点提取、
超长截断）、LLM 摘要路径（成功解析 JSON / 失败回退规则）、extract_key_points
（规则 / LLM 列表解析 / LLM 非列表 / 失败回退）、_format_conversation。
通过 monkeypatch 模块级 Settings 假对象隔离配置。

运行：python -m pytest tests/test_context_summarizer.py -v
"""
import pytest

from server.core.context import summarizer as sm_mod
from server.core.context.summarizer import ContextSummarizer


class _FakeContextLimits:
    summarizer_max_key_points = 15


class _FakeLimits:
    context = _FakeContextLimits()


class _FakeConfig:
    limits = _FakeLimits()


class _FakeSettings:
    def __init__(self):
        self.config = _FakeConfig()


@pytest.fixture(autouse=True)
def _fake_settings(monkeypatch):
    monkeypatch.setattr(sm_mod, "Settings", lambda: _FakeSettings())


def _msgs():
    return [
        {"role": "user", "content": "今天天气怎么样"},
        {"role": "assistant", "content": "今天天气晴朗"},
        {"role": "user", "content": "明天呢"},
        {"role": "assistant", "content": "明天多云"},
    ]


# ---------------------------------------------------------------- 空消息
@pytest.mark.asyncio
async def test_summarize_empty_no_llm():
    assert await ContextSummarizer().summarize([]) == {
        "summary": "", "key_points": [], "success": True,
    }


@pytest.mark.asyncio
async def test_extract_key_points_empty_no_llm():
    assert await ContextSummarizer().extract_key_points([]) == []


# ---------------------------------------------------------------- 规则摘要
@pytest.mark.asyncio
async def test_rule_based_summary_concise():
    res = await ContextSummarizer().summarize(_msgs(), style="concise")
    assert res["success"] is True
    assert "4轮" in res["summary"]
    assert "2次用户提问" in res["summary"]
    assert "2次助手回复" in res["summary"]
    assert len(res["key_points"]) == 2


@pytest.mark.asyncio
async def test_rule_based_summary_detailed():
    res = await ContextSummarizer().summarize(_msgs(), style="detailed")
    assert res["success"] is True
    assert "4轮对话" in res["summary"]
    assert "2次对话" in res["summary"]


@pytest.mark.asyncio
async def test_rule_based_summary_truncates_to_max_length():
    res = await ContextSummarizer().summarize(_msgs(), max_length=20)
    assert len(res["summary"]) <= 20
    assert res["summary"].endswith("...")


@pytest.mark.asyncio
async def test_rule_based_empty_style():
    res = await ContextSummarizer().summarize([], style="concise")
    assert res["summary"] == ""


# ---------------------------------------------------------------- LLM 摘要
class _FakeLLM:
    def __init__(self, content):
        self.content = content

    async def chat(self, messages=None, stream=False):
        return type("R", (), {"content": self.content})()


@pytest.mark.asyncio
async def test_summarize_llm_success():
    llm = _FakeLLM('{"summary": "对话摘要", "key_points": ["要点1"]}')
    res = await ContextSummarizer(llm).summarize(_msgs())
    assert res["summary"] == "对话摘要"
    assert res["key_points"] == ["要点1"]
    assert res["success"] is True


@pytest.mark.asyncio
async def test_summarize_llm_content_missing_falls_back():
    llm = _FakeLLM("{}")
    res = await ContextSummarizer(llm).summarize(_msgs())
    # LLM 返回空对象 → 摘要为空但 marked success
    assert res["summary"] == ""
    assert res["success"] is True


@pytest.mark.asyncio
async def test_summarize_llm_error_falls_back_to_rule():
    class _ErrLLM:
        async def chat(self, messages=None, stream=False):
            raise RuntimeError("boom")

    res = await ContextSummarizer(_ErrLLM()).summarize(_msgs())
    assert res["success"] is True
    assert "轮" in res["summary"]


def test_set_llm_client():
    c = ContextSummarizer()
    llm = _FakeLLM("{}")
    c.set_llm_client(llm)
    assert c.llm_client is llm


# ---------------------------------------------------------------- 关键点
@pytest.mark.asyncio
async def test_extract_key_points_rule_based():
    msgs = [
        {"role": "user", "content": "今天天气怎么样我们出去走走"},
        {"role": "assistant", "content": "好的我们出发吧"},
        {"role": "user", "content": "明天记得带上雨伞和外套"},
        {"role": "assistant", "content": "没问题"},
    ]
    kp = await ContextSummarizer().extract_key_points(msgs)
    assert len(kp) == 2
    assert kp[0].startswith("今天")


@pytest.mark.asyncio
async def test_extract_key_points_rule_based_short_content():
    msgs = [
        {"role": "user", "content": "短"},  # 仅 1 字符，未被纳入
        {"role": "user", "content": "这是一个足够长的用户消息可以超过十个字"},
    ]
    kp = await ContextSummarizer().extract_key_points(msgs)
    assert len(kp) == 1


@pytest.mark.asyncio
async def test_extract_key_points_llm_list():
    llm = _FakeLLM('["要点A", "要点B"]')
    kp = await ContextSummarizer(llm).extract_key_points(_msgs())
    assert kp == ["要点A", "要点B"]


@pytest.mark.asyncio
async def test_extract_key_points_llm_not_list():
    llm = _FakeLLM('{"key": "value"}')
    kp = await ContextSummarizer(llm).extract_key_points(_msgs())
    # 非列表 → 返回规则回退；（_msgs 内容均 <10 字 → 空）
    assert kp == []


@pytest.mark.asyncio
async def test_extract_key_points_llm_error_falls_back():
    class _ErrLLM:
        async def chat(self, messages=None, stream=False):
            raise RuntimeError("boom")

    msgs = [
        {"role": "user", "content": "这是一个足够长的用户消息可以超过十个字"},
    ]
    kp = await ContextSummarizer(_ErrLLM()).extract_key_points(msgs)
    assert len(kp) == 1


# ---------------------------------------------------------------- 格式化
def test_format_conversation():
    c = ContextSummarizer()
    out = c._format_conversation(_msgs())
    assert "user: 今天天气怎么样" in out
    assert out.count("\n") == 3