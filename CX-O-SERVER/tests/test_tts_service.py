"""server.services.tts_service (TTSService) 单元测试。

聚焦可隔离测试的纯逻辑与内部辅助方法，隔离网络（httpx/retry）与 TTS 引擎：

- split_text_streaming：细粒度流式分块（字数阈值 + 停顿标点双触发）

运行：python -m pytest tests/test_tts_service.py -v
"""
import pytest

from server.services.tts_service import TTSService


def _svc(**kw):
    return TTSService(**kw)


# ================================================================ split_text_streaming
class TestSplitTextStreaming:
    async def _collect(self, s, tokens, threshold=3):
        async def gen():
            for t in tokens:
                yield t
        return [chunk async for chunk in s.split_text_streaming(gen(), char_threshold=threshold)]

    @pytest.mark.asyncio
    async def test_splits_on_character_threshold(self):
        s = _svc()
        # 逐字喂入：每达 3 个中文字符切一次，剩余 flush
        chunks = await self._collect(s, list("你好世界大家"), threshold=3)
        assert chunks == ["你好世", "界大家"]

    @pytest.mark.asyncio
    async def test_splits_on_pause_punctuation(self):
        s = _svc()
        # 遇逗号即切片（保留逗号）
        chunks = await self._collect(s, list("你好，世界"), threshold=100)
        assert chunks == ["你好，", "世界"]

    @pytest.mark.asyncio
    async def test_threshold_clamped(self):
        s = _svc()
        # char_threshold 被 clamp 到 2~5；逐字喂入 6 个英文不计数 → 整段 flush
        chunks = await self._collect(s, list("abcdef"), threshold=99)
        assert chunks == ["abcdef"]

    @pytest.mark.asyncio
    async def test_empty_tokens(self):
        s = _svc()
        assert await self._collect(s, []) == []

    @pytest.mark.asyncio
    async def test_non_chinese_not_counted(self):
        s = _svc()
        # 英文不计入中文字数，3 个中文达阈值后切片
        chunks = await self._collect(s, list("ab好好好"), threshold=3)
        # "ab好" + "好好" ？逐字：ab 不计数，好1 好2 好3 达阈值 → 切 "ab好好好"
        assert chunks == ["ab好好好"]

    @pytest.mark.asyncio
    async def test_whitespace_flushed(self):
        s = _svc()
        chunks = await self._collect(s, ["  "])
        assert chunks == []  # 全空白不产出


# ================================================================ 其他
class TestMisc:
    @pytest.mark.asyncio
    async def test_get_voices(self):
        assert await _svc().get_voices() == [{"id": "default", "name": "Default Voice"}]

    @pytest.mark.asyncio
    async def test_initialize_remote(self):
        s = _svc(mode="remote")
        await s.initialize()
        assert s._initialized is True

    def test_mode_property(self):
        assert _svc(mode="remote").mode == "remote"
