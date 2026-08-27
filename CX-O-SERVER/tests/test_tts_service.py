"""server.services.tts_service (TTSService) 单元测试。

聚焦可隔离测试的纯逻辑与内部辅助方法，隔离网络（httpx/retry）与 TTS 引擎：

- split_text_streaming：细粒度流式分块（字数阈值 + 停顿标点双触发）

运行：python -m pytest tests/test_tts_service.py -v
"""
import asyncio

import pytest

from server.services.tts_service import TTSService
from server.core.utils import make_semaphore


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
    async def test_get_voices(self, monkeypatch):
        # #14: get_voices 已接入 ref_audio_store 资产索引（default 兜底 + 资产列表）。
        # 用 monkeypatch 固定资产列表，避免依赖环境数据目录。
        from server import ref_audio_store

        class _FakeAsset:
            id = "a1"
            note = "音色A"
            file_name = None
            prompt = None
            is_deleted = False

        monkeypatch.setattr(ref_audio_store, "list", lambda: [_FakeAsset()])
        voices = await _svc().get_voices()
        assert voices == [
            {"id": "default", "name": "Default Voice"},
            {"id": "a1", "name": "音色A"},
        ]

    @pytest.mark.asyncio
    async def test_get_voices_falls_back_on_asset_error(self, monkeypatch):
        from server import ref_audio_store

        def _boom():
            raise RuntimeError("index unreadable")

        monkeypatch.setattr(ref_audio_store, "list", _boom)
        assert await _svc().get_voices() == [{"id": "default", "name": "Default Voice"}]

    @pytest.mark.asyncio
    async def test_initialize_remote(self):
        s = _svc(mode="remote")
        await s.initialize()
        assert s._initialized is True

    def test_mode_property(self):
        assert _svc(mode="remote").mode == "remote"


# ================================================================ 统一并发信号量背压
class TestConcurrencyGate:
    """TTS synthesize 统一 in-flight 信号量：wait 排队 / drop 拒绝（spec T3）。"""

    @pytest.mark.asyncio
    async def test_wait_mode_serializes_inflight(self):
        # H10 守卫生效：并发门测试需构造已就绪实例（仅用于过入口守卫，
        # 真实合成路径已被 fake 替换）
        s = _svc(qwen3_enabled=True, qwen3_provider=object())
        s._tts_drop = False
        s._tts_limit = 1
        s._tts_sem = make_semaphore(1)
        active = 0
        max_active = 0

        async def fake(text, **kw):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return b"x"

        s._synthesize_qwen3 = fake
        results = await asyncio.gather(*[s.synthesize("hi") for _ in range(5)])
        assert all(r == b"x" for r in results)
        assert max_active <= 1  # 排队语义：任意时刻 in-flight 不超过上限

    @pytest.mark.asyncio
    async def test_drop_mode_rejects_when_saturated(self):
        s = _svc(qwen3_enabled=True, qwen3_provider=object())  # 过 H10 入口守卫
        s._tts_drop = True
        s._tts_limit = 1
        s._tts_sem = make_semaphore(1)
        started = asyncio.Event()
        release = asyncio.Event()
        calls = {"n": 0}

        async def fake(text, **kw):
            calls["n"] += 1
            started.set()
            await release.wait()
            return b"audio"

        s._synthesize_qwen3 = fake
        t1 = asyncio.create_task(s.synthesize("first"))  # 占用信号量
        await started.wait()
        r2 = await s.synthesize("second")  # 已饱和 -> drop 返回空
        assert r2 == b""
        assert calls["n"] == 1  # 仅第一个进入 provider
        release.set()
        assert (await t1) == b"audio"
