"""server.services.live_client (LiveClientHandler) 单元测试。

通过 monkeypatch 模块级单例 getter（get_context_manager / get_firewall_service /
get_frontend_marker / get_adaptive_polling_manager / get_audio_stream_processor /
get_asr_interrupt_module / get_agent_interrupt_module）注入假依赖，覆盖：

- handle_message 消息路由（init/danmaku/gift/enter/config/text/interrupt/stop_tts/未知）
- 各 _handle_* 方法：配置更新、弹幕过滤、上下文写入、ack 响应
- handle_audio：VAD 状态变化、ASR 结果推送、打断判定、vad_frame、轮询记录

运行：python -m pytest tests/test_live_client.py -v
"""
import pytest

from server.services import live_client as lc


# ================================================================ 假依赖
class FakeManager:
    def __init__(self):
        self.sent = []

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


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


class FakePollingManager:
    def __init__(self):
        self.packets = 0

    def record_packet(self):
        self.packets += 1


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

    async def on_asr_result(self, text, is_final=False):
        return "INTERRUPT", True

    def reset_interrupt(self):
        self.reset_count += 1

    def set_config(self, cfg):
        self.configs.append(cfg)


class FakeAgentInterrupt:
    def __init__(self):
        self.configs = []

    def set_config(self, cfg):
        self.configs.append(cfg)


@pytest.fixture
def handler(monkeypatch):
    manager = FakeManager()
    fw = FakeFirewall()
    cm = FakeContextManager()
    fm = FakeFrontendMarker()
    pm = FakePollingManager()
    im = FakeInterruptModule()
    ai = FakeAgentInterrupt()

    monkeypatch.setattr(lc, "get_context_manager", lambda: cm)
    monkeypatch.setattr(lc, "get_firewall_service", lambda: fw)
    monkeypatch.setattr(lc, "get_frontend_marker", lambda: fm)
    monkeypatch.setattr(lc, "get_adaptive_polling_manager", lambda: pm)
    monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda: im)
    monkeypatch.setattr(lc, "get_agent_interrupt_module", lambda: ai)

    h = lc.LiveClientHandler(manager, "c1", {})
    # 重绑定 fixture 内可访问的依赖
    h._manager = manager
    h.firewall = fw
    h.context_manager = cm
    h.frontend_marker = fm
    h._polling_manager = pm
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
        _, msg = handler._manager.sent[0]
        assert msg["type"] == "danmaku"
        assert msg["data"]["formatted"] is True

    @pytest.mark.asyncio
    async def test_danmaku_filtered_no_send(self, handler):
        handler.firewall = FakeFirewall(allowed=False)
        await handler._handle_danmaku(None, {"data": {"content": "x"}})
        assert handler._manager.sent == []
        assert handler.context_manager.danmakus == []


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
        monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda: im)
        monkeypatch.setattr(lc, "get_agent_interrupt_module", lambda: ai)
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
    async def test_text_adds_context_and_acks(self, handler):
        handler._session_id = "s1"
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
        monkeypatch.setattr(lc, "get_audio_stream_processor",
                            lambda: FakeStreamProcessor())
        await handler.handle_audio(None, b"\x00", "c1")
        # 仅 vad_frame
        assert handler._manager.sent[0][1]["type"] == "vad_frame"
        assert handler._polling_manager.packets == 1

    @pytest.mark.asyncio
    async def test_audio_vad_state_change_sends_status(self, handler, monkeypatch):
        vad = {"is_speaking": True, "speech_probability": 0.9,
               "speech_duration_ms": 100, "state_changed": True}
        monkeypatch.setattr(lc, "get_audio_stream_processor",
                            lambda: FakeStreamProcessor(vad=vad))
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
        monkeypatch.setattr(lc, "get_audio_stream_processor",
                            lambda: FakeStreamProcessor(vad=vad, asr=asr))
        monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda: im)
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
        monkeypatch.setattr(lc, "get_audio_stream_processor",
                            lambda: FakeStreamProcessor(vad=vad, asr=asr))
        monkeypatch.setattr(lc, "get_asr_interrupt_module", lambda: im)
        await handler.handle_audio(None, b"\x00", "c1")
        types = [m[1]["type"] for m in handler._manager.sent]
        assert "asr_result" in types
        assert "interrupt" not in types

    @pytest.mark.asyncio
    async def test_audio_exception_swallowed(self, handler, monkeypatch):
        async def boom(audio):
            raise RuntimeError("bad")

        monkeypatch.setattr(lc, "get_audio_stream_processor", lambda: type(
            "P", (), {"process_audio_chunk": boom})())
        await handler.handle_audio(None, b"\x00", "c1")
        assert handler._manager.sent == []  # 异常被捕获，无消息
