"""server.services.live_client (LiveClientHandler) 单元测试。

通过 monkeypatch 模块级单例 getter（get_context_manager / get_firewall_service /
get_frontend_marker / get_audio_stream_processor / get_asr_interrupt_module /
get_agent_interrupt_module）注入假依赖，覆盖：

- handle_message 消息路由（init/danmaku/gift/enter/config/text/interrupt/stop_tts/未知）
- 各 _handle_* 方法：配置更新、弹幕过滤、上下文写入、ack 响应
- handle_audio：VAD 状态变化、ASR 结果推送、打断判定、vad_frame
- W5：gift/enter live 频道广播、stream/response 回复链路、tts_sync/tick/end 字幕播报

运行：python -m pytest tests/test_live_client.py -v
"""
import asyncio

import pytest

from server.services import live_client as lc


# ================================================================ 假依赖
class FakeManager:
    def __init__(self):
        self.sent = []
        self.channel_broadcasts = []

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))

    async def broadcast_to_channel(self, channel, message):
        self.channel_broadcasts.append((channel, message))


class FakeFirewall:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.reason = "" if allowed else "filtered"
        self.configs = []

    def filter_message(self, content, user_id, username):
        return self

    def set_config(self, cfg):
        self.configs.append(cfg)


class FakeContextManager:
    def __init__(self):
        self.danmakus = []
        self.messages = []

    def add_danmaku_message(self, sid, data):
        self.danmakus.append((sid, data))

    def add_message(self, sid, msg):
        self.messages.append((sid, msg))


class FakeFrontendMarker:
    def format_for_frontend(self, marker_data):
        return {"formatted": True, "source": marker_data}


class FakeStreamProcessor:
    def __init__(self, vad=None, asr=None):
        self._vad = vad or {"is_speaking": False, "speech_probability": 0.0,
                            "speech_duration_ms": 0, "state_changed": False}
        self._asr = asr

    async def process_audio_chunk(self, audio_data):
        return {"vad": self._vad, "asr": self._asr}


class FakeInterruptModule:
    def __init__(self, enabled=False, tts_playing=False):
        self.enabled = enabled
        self._tts_playing = tts_playing
        self.reset_count = 0
        self.configs = []
        self.tts_playing_set = []
        self.session_ids = []

    async def on_asr_result(self, text, is_final=False):
        return "INTERRUPT", True

    def set_tts_playing(self, playing):
        self.tts_playing_set.append(playing)

    def reset_interrupt(self):
        self.reset_count += 1

    def set_config(self, cfg):
        self.configs.append(cfg)

    def set_session_id(self, session_id):
        # H1：_handle_init 校正真实会话 id 的注入点
        self.session_ids.append(session_id)


class FakeAgentInterrupt:
    def __init__(self):
        self.configs = []
        self.session_ids = []

    def set_config(self, cfg):
        self.configs.append(cfg)

    def set_session_id(self, session_id):
        self.session_ids.append(session_id)


@pytest.fixture
def handler(monkeypatch):
    manager = FakeManager()
    fw = FakeFirewall()
    cm = FakeContextManager()
    fm = FakeFrontendMarker()
    im = FakeInterruptModule()
    ai = FakeAgentInterrupt()

    monkeypatch.setattr(lc, "get_context_manager", lambda: cm)
    monkeypatch.setattr(lc, "get_firewall_service", lambda: fw)
    monkeypatch.setattr(lc, "get_frontend_marker", lambda: fm)
    monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda client_id=None: im)
    monkeypatch.setattr(lc, "get_agent_interrupt_module", lambda client_id=None: ai)

    h = lc.LiveClientHandler(manager, "c1", {})
    # 重绑定 fixture 内可访问的依赖
    h._manager = manager
    h.firewall = fw
    h.context_manager = cm
    h.frontend_marker = fm
    return h


# ================================================================ 消息路由
class TestRouting:
    @pytest.mark.asyncio
    async def test_routes_known_types(self, handler, monkeypatch):
        called = []
        for t in ["init", "danmaku", "gift", "enter", "config", "text", "interrupt", "stop_tts"]:
            async def fake(ws, msg, _t=t):
                called.append(_t)

            monkeypatch.setattr(handler, f"_handle_{t}", fake)
            await handler.handle_message(None, {"type": t}, "c1")
        assert called == ["init", "danmaku", "gift", "enter", "config", "text", "interrupt", "stop_tts"]

    @pytest.mark.asyncio
    async def test_unknown_type_noop(self, handler):
        await handler.handle_message(None, {"type": "nope"}, "c1")
        assert handler._manager.sent == []

    @pytest.mark.asyncio
    async def test_handle_message_danmaku_data_null_no_raise(self, handler):
        """E1 回归：handle_message 收到 {"type":"danmaku","data":null} 不抛异常。"""
        handler.firewall = FakeFirewall(allowed=False)  # 空内容到此拦截，主路径收束
        await handler.handle_message(None, {"type": "danmaku", "data": None}, "c1")  # 不应抛
        assert handler._manager.channel_broadcasts == []

    @pytest.mark.asyncio
    async def test_handler_exception_sends_error_frame_keeps_loop(self, handler, monkeypatch):
        """E1 回归：分派 handler 抛异常时回发 error 帧且不向上抛（不断连）。"""

        async def boom(ws, msg):
            raise RuntimeError("danmaku explode")

        monkeypatch.setattr(handler, "_handle_danmaku", boom)
        await handler.handle_message(None, {"type": "danmaku", "data": {"content": "x"}}, "c1")
        _, msg = handler._manager.sent[-1]
        assert msg["type"] == "error"


# ================================================================ _handle_init
class TestInit:
    @pytest.mark.asyncio
    async def test_init_updates_config_and_session(self, handler):
        await handler._handle_init(None, {"data": {"session_id": "s1", "foo": 1}})
        assert handler.client_config["foo"] == 1
        assert handler._session_id == "s1"
        _, msg = handler._manager.sent[0]
        assert msg["type"] == "init_ack"
        assert msg["data"]["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_init_default_session_to_client_id(self, handler):
        await handler._handle_init(None, {"data": {}})
        assert handler._session_id == "c1"


# ================================================================ _handle_danmaku
class TestDanmaku:
    @pytest.mark.asyncio
    async def test_danmaku_allowed_sends_frontend(self, handler):
        handler._session_id = "s1"
        data = {"content": "hello", "user": {"uid": "u1", "username": "n1"}}
        await handler._handle_danmaku(None, {"data": data})
        assert handler.context_manager.danmakus == [("s1", data)]
        # 弹幕回显改为 live 频道全房间广播
        assert len(handler._manager.channel_broadcasts) == 1
        channel, msg = handler._manager.channel_broadcasts[0]
        assert channel == "live"
        assert msg["type"] == "danmaku"
        assert msg["data"]["formatted"] is True

    @pytest.mark.asyncio
    async def test_danmaku_filtered_no_send(self, handler):
        handler.firewall = FakeFirewall(allowed=False)
        await handler._handle_danmaku(None, {"data": {"content": "x"}})
        assert handler._manager.sent == []
        assert handler._manager.channel_broadcasts == []
        assert handler.context_manager.danmakus == []

    @pytest.mark.asyncio
    async def test_danmaku_data_null_safe(self, handler):
        """E1 回归：data 为 null 时降级为空对象，不抛 AttributeError。"""
        handler.firewall = FakeFirewall(allowed=False)  # 空内容到此拦截，主路径收束
        await handler._handle_danmaku(None, {"data": None})  # 不应抛
        assert handler._manager.channel_broadcasts == []

    @pytest.mark.asyncio
    async def test_danmaku_user_non_dict_safe(self, handler):
        """E1 回归：user 为非字典时降级为空值，不抛 AttributeError。"""
        handler.firewall = FakeFirewall(allowed=False)
        await handler._handle_danmaku(
            None, {"data": {"content": "hi", "user": "stranger"}})  # 不应抛


# ================================================================ _handle_gift / enter
class TestGift:
    @pytest.mark.asyncio
    async def test_gift_adds_context_and_acks(self, handler):
        handler._session_id = "s1"
        await handler._handle_gift(None, {"data": {"gift": "flower"}})
        assert handler.context_manager.messages[0][0] == "s1"
        assert handler.context_manager.messages[0][1]["role"] == "gift"
        assert handler._manager.sent[0][1]["type"] == "gift_ack"


class TestEnter:
    @pytest.mark.asyncio
    async def test_enter_acks(self, handler):
        await handler._handle_enter(None, {"data": {}})
        assert handler._manager.sent[0][1]["type"] == "enter_ack"


# ================================================================ _handle_config
class TestConfig:
    @pytest.mark.asyncio
    async def test_config_dispatches_submodules(self, handler, monkeypatch):
        fw = FakeFirewall()
        im = FakeInterruptModule()
        ai = FakeAgentInterrupt()
        monkeypatch.setattr(lc, "get_firewall_service", lambda: fw)
        monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda client_id=None: im)
        monkeypatch.setattr(lc, "get_agent_interrupt_module", lambda client_id=None: ai)
        handler.firewall = fw
        data = {"firewall": {"a": 1}, "interrupt": {"b": 2}, "agent_interrupt": {"c": 3}}
        await handler._handle_config(None, {"data": data})
        assert fw.configs == [{"a": 1}]
        assert im.configs == [data]
        assert ai.configs == [data]
        assert handler._manager.sent[0][1]["type"] == "config_ack"

    @pytest.mark.asyncio
    async def test_config_no_keys(self, handler):
        await handler._handle_config(None, {"data": {}})
        assert handler._manager.sent[0][1]["type"] == "config_ack"


# ================================================================ _handle_text / interrupt / stop_tts
class TestText:
    @pytest.mark.asyncio
    async def test_text_adds_context_and_acks(self, handler, monkeypatch):
        handler._session_id = "s1"
        # W5: 屏蔽新增的回复生成调度（本用例仅验证既有上下文写入 + ack 行为）
        monkeypatch.setattr(handler, "_schedule_reply", lambda text: None)
        await handler._handle_text(None, {"data": {"text": "hi"}})
        assert handler.context_manager.messages[0][1] == {"role": "user", "content": "hi"}
        assert handler._manager.sent[0][1]["type"] == "text_ack"


class TestInterrupt:
    @pytest.mark.asyncio
    async def test_interrupt_resets_and_acks(self, handler):
        await handler._handle_interrupt(None, {"data": {}})
        assert handler._manager.sent[0][1]["type"] == "interrupt_ack"


class TestStopTts:
    @pytest.mark.asyncio
    async def test_stop_tts_acks(self, handler, monkeypatch):
        called = []

        async def fake_set(id_, val):
            called.append((id_, val))

        import server.handlers.audio as audio_mod
        monkeypatch.setattr(audio_mod, "set_tts_playing", fake_set)
        await handler._handle_stop_tts(None, {})
        assert called == [("c1", False)]
        assert handler._manager.sent[0][1]["type"] == "stop_tts_ack"


# ================================================================ handle_audio
class TestAudio:
    @pytest.mark.asyncio
    async def test_audio_no_vad_change_no_asr(self, handler, monkeypatch):
        monkeypatch.setattr(lc, "ensure_stream_processor_configured",
                            lambda client_id: FakeStreamProcessor())
        await handler.handle_audio(None, b"\x00", "c1")
        # 仅 vad_frame
        assert handler._manager.sent[0][1]["type"] == "vad_frame"

    @pytest.mark.asyncio
    async def test_audio_resets_voice_context(self, handler, monkeypatch):
        """handle_audio 结束后应复位 voice_context，避免 client_id 残留串扰。"""
        from server.services.voice_context import get_active_client_id
        monkeypatch.setattr(lc, "ensure_stream_processor_configured",
                            lambda client_id: FakeStreamProcessor())
        assert get_active_client_id() == "default"
        await handler.handle_audio(None, b"\x00", "c1")
        assert get_active_client_id() == "default"

    @pytest.mark.asyncio
    async def test_audio_vad_state_change_sends_status(self, handler, monkeypatch):
        vad = {"is_speaking": True, "speech_probability": 0.9,
               "speech_duration_ms": 100, "state_changed": True}
        monkeypatch.setattr(lc, "ensure_stream_processor_configured",
                            lambda client_id: FakeStreamProcessor(vad=vad))
        await handler.handle_audio(None, b"\x00", "c1")
        types = [m[1]["type"] for m in handler._manager.sent]
        assert "vad_status" in types
        assert "vad_frame" in types

    @pytest.mark.asyncio
    async def test_audio_asr_result_and_interrupt(self, handler, monkeypatch):
        vad = {"is_speaking": False, "speech_probability": 0.0,
               "speech_duration_ms": 0, "state_changed": False}
        asr = {"text": "你好"}
        im = FakeInterruptModule(enabled=True, tts_playing=True)
        monkeypatch.setattr(lc, "ensure_stream_processor_configured",
                            lambda client_id: FakeStreamProcessor(vad=vad, asr=asr))
        monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda client_id=None: im)
        await handler.handle_audio(None, b"\x00", "c1")
        types = [m[1]["type"] for m in handler._manager.sent]
        assert "asr_result" in types
        assert "interrupt" in types
        # interrupt 消息数据
        inter = [m[1] for m in handler._manager.sent if m[1]["type"] == "interrupt"][0]
        assert inter["data"]["text"] == "你好"
        assert inter["data"]["source"] == "asr"

    @pytest.mark.asyncio
    async def test_audio_interrupt_disabled_skips(self, handler, monkeypatch):
        vad = {"is_speaking": False, "speech_probability": 0.0,
               "speech_duration_ms": 0, "state_changed": False}
        asr = {"text": "hi"}
        im = FakeInterruptModule(enabled=False, tts_playing=True)
        monkeypatch.setattr(lc, "ensure_stream_processor_configured",
                            lambda client_id: FakeStreamProcessor(vad=vad, asr=asr))
        monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda client_id=None: im)
        await handler.handle_audio(None, b"\x00", "c1")
        types = [m[1]["type"] for m in handler._manager.sent]
        assert "asr_result" in types
        assert "interrupt" not in types

    @pytest.mark.asyncio
    async def test_audio_exception_swallowed(self, handler, monkeypatch):
        async def boom(audio):
            raise RuntimeError("bad")

        monkeypatch.setattr(lc, "ensure_stream_processor_configured", lambda client_id: type(
            "P", (), {"process_audio_chunk": boom})())
        await handler.handle_audio(None, b"\x00", "c1")
        assert handler._manager.sent == []  # 异常被捕获，无消息


# ================================================================ W5: gift/enter 频道广播
class TestGiftBroadcast:
    @pytest.mark.asyncio
    async def test_gift_broadcasts_to_live_channel(self, handler):
        data = {"gift": "flower", "count": 1, "user": {"uid": "u1", "username": "n1"}}
        await handler._handle_gift(None, {"data": data})
        # ack 照旧先行
        assert handler._manager.sent[0][1]["type"] == "gift_ack"
        # W5: 入站礼物事件原样广播给 live 频道
        assert ("live", {"type": "gift", "data": data}) in handler._manager.channel_broadcasts

    @pytest.mark.asyncio
    async def test_gift_broadcast_failure_swallowed(self, handler):
        async def boom(channel, message):
            raise RuntimeError("ws closed")

        handler._manager.broadcast_to_channel = boom
        await handler._handle_gift(None, {"data": {"gift": "flower"}})  # 广播失败不抛
        assert handler._manager.sent[0][1]["type"] == "gift_ack"


class TestEnterBroadcast:
    @pytest.mark.asyncio
    async def test_enter_broadcasts_to_live_channel(self, handler):
        data = {"user": {"uid": "u2", "username": "观众甲"}}
        await handler._handle_enter(None, {"data": data})
        assert handler._manager.sent[0][1]["type"] == "enter_ack"
        assert ("live", {"type": "enter", "data": data}) in handler._manager.channel_broadcasts


# ================================================================ W5: stream/response 回复链路
class FakeLiveLLM:
    """可编程流式 LLM 假件：按预设 chunk 序列产出/抛错。"""

    def __init__(self, chunks=None, error=None):
        self._chunks = chunks or []
        self._error = error
        self.calls = []

    async def stream_chat(self, messages=None, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self._error is not None:
            raise self._error
        for c in self._chunks:
            yield c


@pytest.fixture
def reply_env(monkeypatch, handler):
    """装配 live 回复链路假依赖：默认 agent 配置 + 可编程 LLM + build_messages。

    字幕播报参数同步归零（时长 0ms），回复链路测试不因播报 sleep 变慢。
    """
    agent_cfg = {
        "id": "default", "name": "小助手", "system_prompt": "你是主播助手",
        "model": "main", "temperature": 0.5, "max_tokens": 4096,
    }

    async def fake_cfg(agent_id):
        return agent_cfg if agent_id == "default" else None

    llm = FakeLiveLLM()
    monkeypatch.setattr("server.chat_helpers.get_agent_config_async", fake_cfg)
    monkeypatch.setattr("server.chat_helpers.get_llm_client_for_agent", lambda cfg: llm)
    monkeypatch.setattr(
        "server.prompt_builder.build_messages",
        lambda cfg, cm, sid, text, **kw: [{"role": "user", "content": text}],
    )
    monkeypatch.setattr(lc, "_LIVE_TTS_MIN_DURATION_MS", 0)
    monkeypatch.setattr(lc, "_LIVE_TTS_MS_PER_CHAR", 0)
    monkeypatch.setattr(lc, "_LIVE_TTS_TICK_INTERVAL", 0.001)

    feedback = []
    monkeypatch.setattr(
        handler, "record_ai_response",
        lambda text, prompt="", ts=None: feedback.append((text, prompt)),
    )
    return handler, llm, feedback


class TestLiveReplyPipeline:
    @pytest.mark.asyncio
    async def test_stream_chunks_then_response(self, reply_env):
        handler, llm, feedback = reply_env
        llm._chunks = [
            {"type": "thinking", "content": "..."},
            {"type": "content", "content": "你"},
            {"type": "content", "content": "好呀"},
            "！",
        ]
        await handler._reply_pipeline("大家好")
        msgs = [m for _, m in handler._manager.channel_broadcasts]
        types = [m["type"] for m in msgs]
        # thinking 不外发；content chunk 逐个 stream
        assert "thinking" not in types
        streams = [m["data"]["content"] for m in msgs if m["type"] == "stream"]
        assert streams == ["你", "好呀", "！"]
        resp = [m for m in msgs if m["type"] == "response"]
        assert len(resp) == 1
        assert resp[0]["data"]["content"] == "你好呀！"

    @pytest.mark.asyncio
    async def test_reply_context_feedback_and_subtitle(self, reply_env):
        handler, llm, feedback = reply_env
        handler._session_id = "s1"
        llm._chunks = [{"type": "content", "content": "收到！"}]
        await handler._reply_pipeline("hi")
        # 上下文回写 assistant
        assert ("s1", {"role": "assistant", "content": "收到！"}) in handler.context_manager.messages
        # 隐式反馈记录（既有增量接入点被打通）
        assert feedback == [("收到！", "hi")]
        # 字幕播报同步随回复触发
        types = [m["type"] for _, m in handler._manager.channel_broadcasts]
        assert types[0] == "stream" and "tts_sync" in types and "tts_end" in types

    @pytest.mark.asyncio
    async def test_llm_error_swallowed(self, reply_env):
        handler, llm, feedback = reply_env
        llm._error = RuntimeError("llm down")
        await handler._reply_pipeline("hi")  # 不抛异常
        assert handler._manager.channel_broadcasts == []
        assert feedback == []

    @pytest.mark.asyncio
    async def test_no_default_agent_skips(self, handler, monkeypatch):
        async def none_cfg(agent_id):
            return None

        monkeypatch.setattr("server.chat_helpers.get_agent_config_async", none_cfg)
        await handler._reply_pipeline("hi")
        assert handler._manager.channel_broadcasts == []

    @pytest.mark.asyncio
    async def test_empty_reply_no_response_frame(self, reply_env):
        handler, llm, feedback = reply_env
        llm._chunks = [{"type": "thinking", "content": "x"}]
        await handler._reply_pipeline("hi")
        types = [m["type"] for _, m in handler._manager.channel_broadcasts]
        assert "response" not in types
        assert feedback == []


class TestScheduleReply:
    @pytest.mark.asyncio
    async def test_schedule_creates_tracked_task(self, handler, monkeypatch):
        called = []

        async def fake_pipeline(text):
            called.append(text)

        monkeypatch.setattr(handler, "_reply_pipeline", fake_pipeline)
        handler._schedule_reply("hi")
        assert handler._reply_task is not None
        await handler._reply_task
        assert called == ["hi"]
        # 完成回调已从模块强引用集清理
        assert handler._reply_task not in lc._reply_tasks

    @pytest.mark.asyncio
    async def test_inflight_guard_drops_new_request(self, handler, monkeypatch):
        async def slow_pipeline(text):
            await asyncio.sleep(10)

        monkeypatch.setattr(handler, "_reply_pipeline", slow_pipeline)
        handler._schedule_reply("first")
        first = handler._reply_task
        handler._schedule_reply("second")  # 在途 → 丢弃本轮
        assert handler._reply_task is first
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_blank_text_no_task(self, handler):
        handler._schedule_reply("   ")
        assert handler._reply_task is None

    @pytest.mark.asyncio
    async def test_handle_text_schedules_reply(self, handler, monkeypatch):
        scheduled = []
        monkeypatch.setattr(handler, "_schedule_reply", lambda text: scheduled.append(text))
        await handler._handle_text(None, {"data": {"text": "hi"}})
        assert scheduled == ["hi"]
        assert handler._manager.sent[0][1]["type"] == "text_ack"


# ================================================================ W5: 字幕播报同步
class TestSubtitleSync:
    @pytest.mark.asyncio
    async def test_sentence_sync_tick_end_sequence(self, handler, monkeypatch):
        monkeypatch.setattr(lc, "_LIVE_TTS_MIN_DURATION_MS", 60)
        monkeypatch.setattr(lc, "_LIVE_TTS_MS_PER_CHAR", 20)
        monkeypatch.setattr(lc, "_LIVE_TTS_TICK_INTERVAL", 0.002)
        await handler._announce_reply_subtitles("你好。世界！")
        msgs = [m for _, m in handler._manager.channel_broadcasts]
        types = [m["type"] for m in msgs]
        # 两句各自 sync→tick*→end
        assert types.count("tts_sync") == 2
        assert types.count("tts_end") == 2
        assert types.count("tts_tick") >= 2
        syncs = [m for m in msgs if m["type"] == "tts_sync"]
        assert [m["data"]["text"] for m in syncs] == ["你好。", "世界！"]
        for s in syncs:
            pid = s["data"]["playback_id"]
            # 字段契约与前端 TTSSyncData/TTSTickData/TTSEndData 一致
            assert set(s["data"].keys()) == {"playback_id", "server_ts", "text", "duration"}
            ends = [m for m in msgs if m["type"] == "tts_end" and m["data"]["playback_id"] == pid]
            assert len(ends) == 1
            assert set(ends[0]["data"].keys()) == {"playback_id", "server_ts"}
            ticks = [m for m in msgs if m["type"] == "tts_tick" and m["data"]["playback_id"] == pid]
            assert len(ticks) >= 1
            assert set(ticks[0]["data"].keys()) == {"playback_id", "server_ts", "position"}
            positions = [t["data"]["position"] for t in ticks]
            assert positions == sorted(positions)  # position 单调不减
        # playback_id 逐句独立
        assert syncs[0]["data"]["playback_id"] != syncs[1]["data"]["playback_id"]

    @pytest.mark.asyncio
    async def test_channel_failure_stops_advance(self, handler, monkeypatch):
        # 第 1 次广播成功（tts_sync），其后失败 → 停止推进且不抛异常
        calls = {"n": 0}

        async def flaky(channel, message):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("closed")
            handler._manager.channel_broadcasts.append((channel, message))

        handler._manager.broadcast_to_channel = flaky
        monkeypatch.setattr(lc, "_LIVE_TTS_MIN_DURATION_MS", 0)
        monkeypatch.setattr(lc, "_LIVE_TTS_MS_PER_CHAR", 0)
        monkeypatch.setattr(lc, "_LIVE_TTS_TICK_INTERVAL", 0.001)
        await handler._announce_reply_subtitles("第一句。第二句！")
        syncs = [m for _, m in handler._manager.channel_broadcasts if m["type"] == "tts_sync"]
        assert len(syncs) == 1  # 第二句未推进

    @pytest.mark.asyncio
    async def test_unterminated_text_single_sentence(self, handler, monkeypatch):
        monkeypatch.setattr(lc, "_LIVE_TTS_MIN_DURATION_MS", 0)
        monkeypatch.setattr(lc, "_LIVE_TTS_MS_PER_CHAR", 0)
        monkeypatch.setattr(lc, "_LIVE_TTS_TICK_INTERVAL", 0.001)
        await handler._announce_reply_subtitles("无标点结尾")
        syncs = [m for _, m in handler._manager.channel_broadcasts if m["type"] == "tts_sync"]
        assert [m["data"]["text"] for m in syncs] == ["无标点结尾"]
