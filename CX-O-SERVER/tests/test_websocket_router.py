"""
server/api/routers/websocket.py 回归测试
LiveTTSSyncBroadcaster 直播 TTS 播放同步广播器：start/end 播放同步、tick 广播、单例。
用 FakeWSManager 隔离真实 WebSocket 网络，monkeypatch asyncio.sleep 加速 tick 循环。
"""
import asyncio
import time

import pytest

import server.api.routers.websocket as ws_mod
from server.api.routers.websocket import LiveTTSSyncBroadcaster, get_tts_sync_broadcaster


class FakeWSManager:
    """记录 broadcast_to_channel 调用，隔离真实 WebSocket 网络。"""

    def __init__(self):
        self.broadcasted = []

    async def broadcast_to_channel(self, channel, message):
        self.broadcasted.append((channel, message))


@pytest.fixture
def fake_mgr(monkeypatch):
    mgr = FakeWSManager()
    monkeypatch.setattr(ws_mod, "get_websocket_manager", lambda: mgr)
    return mgr


@pytest.fixture
def broadcaster(fake_mgr):
    return LiveTTSSyncBroadcaster()


@pytest.fixture
def fast_sleep(monkeypatch):
    """让 asyncio.sleep 立即返回，加速 tick 循环。"""

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(ws_mod.asyncio, "sleep", _noop)


def _broadcast_types(fake_mgr):
    return [m["type"] for _, m in fake_mgr.broadcasted]


class TestSingleton:
    def test_get_tts_sync_broadcaster_singleton(self, monkeypatch):
        monkeypatch.setattr(ws_mod, "_tts_sync_broadcaster", None)
        b = get_tts_sync_broadcaster()
        assert b is get_tts_sync_broadcaster()

    def test_get_tts_sync_broadcaster_reuses_existing(self, monkeypatch):
        existing = LiveTTSSyncBroadcaster()
        monkeypatch.setattr(ws_mod, "_tts_sync_broadcaster", existing)
        assert get_tts_sync_broadcaster() is existing


class TestStartPlayback:
    @pytest.mark.asyncio
    async def test_broadcasts_tts_sync(self, broadcaster, fake_mgr, fast_sleep):
        await broadcaster.start_playback("你好", 5000)
        try:
            assert broadcaster._running is True
            assert broadcaster._duration == 5000
            assert broadcaster._text == "你好"
            assert len(broadcaster._current_playback_id) == 12
            assert broadcaster._tick_task is not None

            channel, msg = fake_mgr.broadcasted[0]
            assert channel == "live"
            assert msg["type"] == "tts_sync"
            data = msg["data"]
            assert data["playback_id"] == broadcaster._current_playback_id
            assert data["text"] == "你好"
            assert data["duration"] == 5000
            assert isinstance(data["server_ts"], int)
        finally:
            await broadcaster.end_playback()

    @pytest.mark.asyncio
    async def test_start_ends_previous_playback(self, broadcaster, fake_mgr, fast_sleep):
        await broadcaster.start_playback("一段", 1000)
        await broadcaster.start_playback("二段", 2000)
        try:
            # 第二次 start 会先 end 前一次 → 至少一条 tts_end
            assert "tts_end" in _broadcast_types(fake_mgr)
            # 最终 current_playback_id 是第二次的
            assert broadcaster._text == "二段"
            assert broadcaster._duration == 2000
        finally:
            await broadcaster.end_playback()


class TestEndPlayback:
    @pytest.mark.asyncio
    async def test_end_with_playback_broadcasts_end(self, broadcaster, fake_mgr):
        broadcaster._current_playback_id = "abc123"
        await broadcaster.end_playback()
        channel, msg = fake_mgr.broadcasted[0]
        assert channel == "live"
        assert msg["type"] == "tts_end"
        assert msg["data"]["playback_id"] == "abc123"
        assert broadcaster._current_playback_id is None
        assert broadcaster._running is False

    @pytest.mark.asyncio
    async def test_end_without_playback_noop(self, broadcaster, fake_mgr):
        await broadcaster.end_playback()
        assert fake_mgr.broadcasted == []


class TestTickLoop:
    @pytest.mark.asyncio
    async def test_tick_broadcasts_and_stops_at_duration(self, broadcaster, fake_mgr, fast_sleep):
        # 让 elapsed(由 monotonic 推演) 超过 duration → 首轮即达终点
        broadcaster._running = True
        broadcaster._duration = 100
        broadcaster._start_time = time.monotonic() - 1.0
        broadcaster._current_playback_id = "tid1"

        await broadcaster._tick_loop()

        types = _broadcast_types(fake_mgr)
        assert "tts_tick" in types
        if "tts_tick" in types:
            channel, msg = fake_mgr.broadcasted[0]
            assert msg["type"] == "tts_tick"
            assert msg["data"]["playback_id"] == "tid1"
            assert msg["data"]["position"] == 100  # min(elapsed, duration)
        # 循环结束后 running 被复位且发出 tts_end
        assert "tts_end" in types
        assert broadcaster._running is False

    @pytest.mark.asyncio
    async def test_tick_loop_noop_when_not_running(self, broadcaster, fake_mgr, fast_sleep):
        broadcaster._running = False
        await broadcaster._tick_loop()
        assert fake_mgr.broadcasted == []

    @pytest.mark.asyncio
    async def test_tick_loop_cancelled_finishes(self, broadcaster, fake_mgr, fast_sleep):
        # 第一次 sleep 抛 CancelledError → 捕获后 finally 调 end_playback 发 tts_end
        broadcaster._running = True
        broadcaster._duration = 1000
        broadcaster._start_time = time.monotonic()
        broadcaster._current_playback_id = "cid"

        orig_sleep = ws_mod.asyncio.sleep

        async def _cancel_sleep(*a, **k):
            raise asyncio.CancelledError()

        ws_mod.asyncio.sleep = _cancel_sleep
        try:
            await broadcaster._tick_loop()
        finally:
            ws_mod.asyncio.sleep = orig_sleep

        assert "tts_end" in _broadcast_types(fake_mgr)