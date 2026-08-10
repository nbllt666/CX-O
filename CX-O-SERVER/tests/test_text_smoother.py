"""
server/services/text_smoother.py 回归测试
LLM-TTS 文本平滑缓冲器：窗口/标点/字数触发 + 流结束收尾
"""
import asyncio

import pytest

from server.services.text_smoother import TextSmoother


class TestParamClamping:
    def test_window_ms_clamped(self):
        assert TextSmoother(window_ms=10)._window_ms == 30
        assert TextSmoother(window_ms=100)._window_ms == 50
        assert TextSmoother(window_ms=40)._window_ms == 40

    def test_char_threshold_clamped(self):
        assert TextSmoother(char_threshold=1)._char_threshold == 2
        assert TextSmoother(char_threshold=99)._char_threshold == 5
        assert TextSmoother(char_threshold=4)._char_threshold == 4


class TestExtractText:
    def test_str_token(self):
        t = TextSmoother()
        assert t._extract_text("你好") == "你好"

    def test_dict_content(self):
        t = TextSmoother()
        assert t._extract_text({"type": "content", "content": "hi"}) == "hi"

    def test_dict_control_message_skipped(self):
        t = TextSmoother()
        assert t._extract_text({"type": "done"}) == ""
        assert t._extract_text({"type": "status"}) == ""
        assert t._extract_text({"type": "error"}) == ""

    def test_dict_ollama_message_format(self):
        t = TextSmoother()
        assert t._extract_text({"message": {"role": "assistant", "content": "ok"}}) == "ok"

    def test_dict_no_text_returns_empty(self):
        t = TextSmoother()
        assert t._extract_text({"type": "content"}) == ""
        assert t._extract_text({}) == ""


@pytest.mark.asyncio
class TestPutFinish:
    async def test_put_after_finish_ignored(self):
        t = TextSmoother()
        await t.finish()
        await t.put("x")  # 不抛异常
        assert t._finished is True

    async def test_finish_idempotent(self):
        t = TextSmoother()
        await t.finish()
        await t.finish()  # 幂等
        assert t._finished is True

    async def test_put_empty_token_not_queued(self):
        t = TextSmoother()
        await t.put({"type": "done"})
        await t.finish()  # 投递结束哨兵，避免 smooth_stream 永久阻塞
        chunks = [c async for c in t.smooth_stream()]
        assert chunks == []


async def _collect(smoother, tokens):
    """投递 tokens 并 finish，收集平滑输出。"""
    for tok in tokens:
        await smoother.put(tok)
    await smoother.finish()
    return [c async for c in smoother.smooth_stream()]


@pytest.mark.asyncio
class TestSmoothStream:
    async def test_empty_stream(self):
        t = TextSmoother(window_ms=30, char_threshold=2)
        chunks = await _collect(t, [])
        assert chunks == []

    async def test_punctuation_triggers_flush(self):
        # 标点触发：逗号后立即 flush
        t = TextSmoother(window_ms=100, char_threshold=5)
        chunks = await _collect(t, ["你好，", "世界"])
        # "你好，" 因标点切出（保留标点）
        assert chunks == ["你好，", "世界"]

    async def test_char_threshold_triggers_flush(self):
        # 字数触发：达到阈值立即切分
        t = TextSmoother(window_ms=100, char_threshold=4)
        chunks = await _collect(t, ["一二三四五", "六七八九十"])
        assert "".join(chunks) == "一二三四五六七八九十"
        assert len("".join(chunks)) == 10

    async def test_end_of_stream_flushes_remaining(self):
        t = TextSmoother(window_ms=50, char_threshold=5)
        chunks = await _collect(t, ["结尾未分段内容"])
        assert chunks == ["结尾未分段内容"]

    async def test_window_timeout_flushes(self):
        # 窗口超时：仅累积"短"后进入迭代，等待 30ms 窗口超时切出该 chunk
        t = TextSmoother(window_ms=30, char_threshold=5)
        await t.put("短")
        first = asyncio.create_task(t.smooth_stream().__anext__())
        chunk = await asyncio.wait_for(first, timeout=1.0)
        assert chunk == "短"


@pytest.mark.asyncio
class TestSmoothClassmethod:
    async def test_smooth_wraps_stream(self):
        async def _tok_stream():
            for tok in ["你好，", "世界"]:
                yield tok

        chunks = [c async for c in TextSmoother.smooth(_tok_stream(), window_ms=100, char_threshold=5)]
        assert chunks == ["你好，", "世界"]

    async def test_smooth_handles_str_and_dict(self):
        async def _tok_stream():
            yield "混合"
            yield {"type": "content", "content": "内容"}
            yield {"type": "done"}

        chunks = [c async for c in TextSmoother.smooth(_tok_stream(), window_ms=100, char_threshold=2)]
        assert "".join(chunks) == "混合内容"

    async def test_smooth_consumer_early_exit_cleans_feeder(self):
        # 消费者取首个 chunk 后提前退出，smooth 应清理 feeder 且不挂起/泄漏。
        # 用有限流避免遗留 feeder 任务占用事件循环导致 teardown 挂起。
        async def _tok_stream():
            for _ in range(100):
                yield "a"

        async def _consume():
            async for _ in TextSmoother.smooth(_tok_stream(), window_ms=30, char_threshold=2):
                return

        await asyncio.wait_for(_consume(), timeout=1.0)