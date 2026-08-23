"""
server/handlers/audio.py 回归测试
音频处理器：set_tts_playing/is_tts_playing 播放状态、cleanup_dual_stream_session 清理、
DualStreamSession 触发状态机（on_partial_result/on_final_result）、_build_tts_kwargs 参考音频参数、
emotion/effect 列表与解析处理器
"""
import base64

import pytest

import server.services.asr_interrupt as asr_interrupt_mod
import server.handlers.audio as audio_mod
from server.handlers.audio import (
    DualStreamSession,
    set_tts_playing,
    cleanup_dual_stream_session,
    register_audio_handlers,
)
from server.protocol.actions import EmotionActions, EffectActions


# --------------------------------------------------------------------------- #
# Fake 集合
# --------------------------------------------------------------------------- #
class FakeManager:
    def __init__(self):
        self.handlers = {}
        self.sent = []
        self.connections = set()

    def register_handler(self, action, handler):
        self.handlers[action] = handler

    def register_action_handler(self, action, handler):
        self.handlers[action] = handler

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


class FakeTTSService:
    def __init__(self):
        self.calls = {}

    async def synthesize(self, text, **kwargs):
        self.calls["synthesize"] = (text, kwargs)
        return b"\x00\x01"

    async def synthesize_stream(self, text, **kwargs):
        yield {"text_segment": "你", "audio_data": b"\x00", "is_final": False}
        yield {"text_segment": "好", "audio_data": b"\x01", "is_final": True}

    async def synthesize_stream_with_emotions(self, text, **kwargs):
        yield {"text_segment": "哈", "audio_data": b"\x00", "emotion": "happy",
               "is_effect": False, "effect_name": None, "is_final": True}


class FakeInterruptModule:
    def __init__(self):
        self.tts_playing = None
        self.enabled = True
        self.calls = []

    def set_tts_playing(self, playing):
        self.tts_playing = playing

    def on_user_speech_start(self):
        self.calls.append("speech_start")

    def on_user_speech_end(self):
        self.calls.append("speech_end")


# --------------------------------------------------------------------------- #
# set_tts_playing
# --------------------------------------------------------------------------- #
class TestTTSPlayingState:
    @pytest.mark.asyncio
    async def test_set_and_clear(self, monkeypatch):
        fake_interrupt = FakeInterruptModule()
        monkeypatch.setattr(audio_mod, "_tts_playing_clients", set())
        # set_tts_playing 在函数体内 from server.services.asr_interrupt import ...
        monkeypatch.setattr(asr_interrupt_mod, "get_asr_interrupt_module",
                            lambda: fake_interrupt)
        assert len(audio_mod._tts_playing_clients) == 0
        await set_tts_playing("c1", True)
        assert "c1" in audio_mod._tts_playing_clients
        assert fake_interrupt.tts_playing is True
        # 多客户端任一在播即为 True
        await set_tts_playing("c2", True)
        assert {"c1", "c2"} <= audio_mod._tts_playing_clients
        # 移除一个后仍为 True
        await set_tts_playing("c1", False)
        assert "c1" not in audio_mod._tts_playing_clients
        assert "c2" in audio_mod._tts_playing_clients
        # 全部移除后为 False
        await set_tts_playing("c2", False)
        assert len(audio_mod._tts_playing_clients) == 0
        assert fake_interrupt.tts_playing is False


# --------------------------------------------------------------------------- #
# cleanup_dual_stream_session
# --------------------------------------------------------------------------- #
class TestCleanupDualStreamSession:
    @pytest.mark.asyncio
    async def test_cleanup_existing(self, monkeypatch):
        monkeypatch.setattr(audio_mod, "_dual_stream_sessions", {})
        mgr = FakeManager()
        session = DualStreamSession(
            client_id="c1", agent_id="a1", request_id="r1", manager=mgr,
            tts_service=FakeTTSService())
        audio_mod._dual_stream_sessions["c1"] = session
        finished = []
        async def fake_finish():
            finished.append(True)
        session.finish = fake_finish
        await cleanup_dual_stream_session("c1")
        assert "c1" not in audio_mod._dual_stream_sessions
        assert finished == [True]

    @pytest.mark.asyncio
    async def test_cleanup_missing(self, monkeypatch):
        monkeypatch.setattr(audio_mod, "_dual_stream_sessions", {})
        await cleanup_dual_stream_session("ghost")  # 无会话，静默 no-op


# --------------------------------------------------------------------------- #
# _build_tts_kwargs
# --------------------------------------------------------------------------- #
class TestBuildTTSKwargs:
    def _session(self, **kw):
        mgr = FakeManager()
        return DualStreamSession(
            client_id="c1", agent_id="a1", request_id="r1", manager=mgr,
            tts_service=FakeTTSService(),
            ref_audio_path=kw.get("ref_audio_path"),
            ref_text=kw.get("ref_text"),
            ref_asset_id=kw.get("ref_asset_id"),
            refs=kw.get("refs"),
        )

    def test_qwen3_asset(self):
        s = self._session(ref_asset_id="ref_abc", refs=[{"asset_id": "ref_abc"}])
        assert s._build_tts_kwargs() == {"ref_asset_id": "ref_abc", "refs": [{"asset_id": "ref_abc"}]}

    def test_f5_with_refs(self):
        s = self._session(ref_audio_path="/x/a.wav", ref_text="你好")
        assert s._build_tts_kwargs() == {"ref_audio_path": "/x/a.wav", "ref_text": "你好"}

    def test_f5_no_refs(self):
        s = self._session()
        assert s._build_tts_kwargs() == {}


# --------------------------------------------------------------------------- #
# DualStreamSession 触发状态机
# --------------------------------------------------------------------------- #
class TestDualStreamSessionTriggers:
    def _session(self, monkeypatch):
        mgr = FakeManager()
        session = DualStreamSession(
            client_id="c1", agent_id="a1", request_id="r1", manager=mgr,
            tts_service=FakeTTSService())
        pipeline_ran = []
        async def fake_pipeline(text):
            pipeline_ran.append(text)
        session._run_pipeline = fake_pipeline
        return session, mgr, pipeline_ran

    @pytest.mark.asyncio
    async def _flush_pipeline(self, session):
        # on_partial_result/on_final_result 用 create_task 启动流水线，需手动 await 让 fake 执行
        if session._pipeline_task:
            await session._pipeline_task

    @pytest.mark.asyncio
    async def test_partial_empty_text_no_trigger(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        await session.on_partial_result({"text": "   ", "is_final": False})
        await self._flush_pipeline(session)
        assert ran == []
        assert session._has_triggered_this_utterance is False

    @pytest.mark.asyncio
    async def test_partial_short_no_trigger(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        await session.on_partial_result({"text": "一", "is_final": False})
        await self._flush_pipeline(session)
        assert ran == []

    @pytest.mark.asyncio
    async def test_partial_reaches_threshold_triggers(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        # 延续性确认：首帧缓存候选不触发，需下一帧延续/复现才确认
        await session.on_partial_result({"text": "你好", "is_final": False})
        await self._flush_pipeline(session)
        assert ran == []
        await session.on_partial_result({"text": "你好", "is_final": False})
        await self._flush_pipeline(session)
        assert ran == ["你好"]
        assert session._has_triggered_this_utterance is True
        # 同一 utterance 后续 partial 不再重复触发
        await session.on_partial_result({"text": "你好世界", "is_final": False})
        await self._flush_pipeline(session)
        assert ran == ["你好"]

    @pytest.mark.asyncio
    async def test_partial_merges_pending(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        session._pending_user_text = "前一句"
        # 延续性确认：首帧缓存，第二帧延续/复现后确认并合并 pending
        await session.on_partial_result({"text": "你好", "is_final": False})
        await self._flush_pipeline(session)
        assert ran == []
        await session.on_partial_result({"text": "你好", "is_final": False})
        await self._flush_pipeline(session)
        assert ran == ["前一句 你好"]
        assert session._pending_user_text == ""

    @pytest.mark.asyncio
    async def test_final_short_accumulates_pending(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        await session.on_final_result({"text": "一", "is_final": True})
        await self._flush_pipeline(session)
        assert ran == []
        assert session._pending_user_text == "一"

    @pytest.mark.asyncio
    async def test_final_speaking_only_pending(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        # is_speaking=True（用户已开说下一句）→ 仅累积 pending，不触发
        await session.on_final_result({"text": "你好世界", "is_final": True}, is_speaking=True)
        await self._flush_pipeline(session)
        assert ran == []
        assert session._pending_user_text == "你好世界"

    @pytest.mark.asyncio
    async def test_final_fallback_trigger(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        await session.on_final_result({"text": "触发吧", "is_final": True})
        await self._flush_pipeline(session)
        # on_final_result 兜底路径自行调度 _finalize_turn，先 await pipeline 再 await finalize
        assert ran == ["触发吧"]
        assert session._has_triggered_this_utterance is True

    @pytest.mark.asyncio
    async def test_final_already_triggered_only_corrects(self, monkeypatch):
        session, mgr, ran = self._session(monkeypatch)
        session._has_triggered_this_utterance = True
        await session.on_final_result({"text": "更准确文本", "is_final": True})
        await self._flush_pipeline(session)
        assert ran == []
        assert session._final_user_text == "更准确文本"


# --------------------------------------------------------------------------- #
# emotion / effect 处理器
# --------------------------------------------------------------------------- #
@pytest.fixture
def handlers():
    mgr = FakeManager()
    tts = FakeTTSService()
    register_audio_handlers(mgr, asr_service=None, tts_service=tts)
    return mgr.handlers, mgr


def _err(mgr):
    msg = mgr.sent[-1][1]
    assert msg["type"] == "error"
    return msg["error"]["code"], msg["error"]["message"]


class TestEmotionHandlers:
    @pytest.mark.asyncio
    async def test_emotions_list(self, handlers):
        h, mgr = handlers
        await h[EmotionActions.LIST](None, {"request_id": "r1", "data": {}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["action"] == EmotionActions.LIST
        assert isinstance(msg["data"]["emotions"], list)

    @pytest.mark.asyncio
    async def test_emotions_parse_success(self, handlers):
        h, mgr = handlers
        await h[EmotionActions.PARSE](None, {"data": {"text": "哈哈哈"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["data"]["segments"] is not None

    @pytest.mark.asyncio
    async def test_emotions_parse_empty_text(self, handlers):
        h, mgr = handlers
        await h[EmotionActions.PARSE](None, {"data": {"text": ""}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"
        assert "Missing text" in msg


class TestEffectHandlers:
    @pytest.mark.asyncio
    async def test_effects_list(self, handlers):
        h, mgr = handlers
        await h[EffectActions.LIST](None, {"data": {}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["action"] == EffectActions.LIST

    @pytest.mark.asyncio
    async def test_effects_parse_success(self, handlers):
        h, mgr = handlers
        await h[EffectActions.PARSE](None, {"data": {"text": "【风铃】叮"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["data"]["segments"] is not None

    @pytest.mark.asyncio
    async def test_effects_parse_empty_text(self, handlers):
        h, mgr = handlers
        await h[EffectActions.PARSE](None, {"data": {"text": ""}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"
        assert "Missing text" in msg


# --------------------------------------------------------------------------- #
# ASR/TTS 处理器
# --------------------------------------------------------------------------- #
class TestASRTTSSynthesize:
    @pytest.mark.asyncio
    async def test_asr_recognize_missing_audio(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import ASRActions
        await h[ASRActions.RECOGNIZE](None, {"data": {}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"
        assert "Missing audio data" in msg

    @pytest.mark.asyncio
    async def test_tts_synthesize_success(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import TTSActions
        await h[TTSActions.SYNTHESIZE](None, {"data": {"text": "你好"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["data"]["format"] == "wav"
        # audio 已 base64 编码
        base64.b64decode(msg["data"]["audio_data"])

    @pytest.mark.asyncio
    async def test_tts_synthesize_missing_text(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import TTSActions
        await h[TTSActions.SYNTHESIZE](None, {"data": {}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"
        assert "Missing text" in msg

    @pytest.mark.asyncio
    async def test_tts_synthesize_stream_success(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import TTSActions
        await h[TTSActions.SYNTHESIZE_STREAM](None, {"data": {"text": "你好"}}, "c1")
        streams = [m for m in mgr.sent if m[1]["type"] == "stream"]
        assert len(streams) == 2
        assert streams[0][1]["data"]["audio_data"] is not None
        # is_final 位于 stream 消息顶层（不在 data 内）
        assert streams[1][1].get("is_final") is True

    @pytest.mark.asyncio
    async def test_tts_synthesize_stream_emotions(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import TTSActions
        await h[TTSActions.SYNTHESIZE_STREAM](
            None, {"data": {"text": "你好", "emotion_enabled": True}}, "c1")
        streams = [m for m in mgr.sent if m[1]["type"] == "stream"]
        assert len(streams) == 1
        assert streams[0][1]["data"]["emotion"] == "happy"


# --------------------------------------------------------------------------- #
# 双流式 handler
# --------------------------------------------------------------------------- #
class TestVoiceDualStream:
    @pytest.mark.asyncio
    async def test_stream_before_init(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import VoiceActions
        await h[VoiceActions.DUAL_STREAM](None, {"data": {"audio": "AAAA"}}, "c1")
        code, msg = _err(mgr)
        assert code == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_init_success(self, handlers, monkeypatch):
        h, mgr = handlers
        from server.protocol.actions import VoiceActions
        await h[VoiceActions.DUAL_STREAM](
            None, {"request_id": "r1", "data": {"init": True, "agent_id": "a1"}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["type"] == "response"
        assert msg["data"]["status"] == "initialized"
        assert "c1" in audio_mod._dual_stream_sessions

    @pytest.mark.asyncio
    async def test_end_session(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import VoiceActions
        await h[VoiceActions.DUAL_STREAM](
            None, {"data": {"init": True, "agent_id": "a1"}}, "c1")
        await h[VoiceActions.DUAL_STREAM](None, {"data": {"end": True}}, "c1")
        msg = mgr.sent[-1][1]
        assert msg["data"]["status"] == "ended"
        assert "c1" not in audio_mod._dual_stream_sessions

    @pytest.mark.asyncio
    async def test_audio_missing(self, handlers):
        h, mgr = handlers
        from server.protocol.actions import VoiceActions
        await h[VoiceActions.DUAL_STREAM](
            None, {"data": {"init": True, "agent_id": "a1"}}, "c1")
        await h[VoiceActions.DUAL_STREAM](None, {"data": {}}, "c1")
        code, msg = _err(mgr)
        assert code == "INVALID_REQUEST"


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    audio_mod._dual_stream_sessions.clear()


# --------------------------------------------------------------------------- #
# 快速记忆模式（voice_memory_fast）：检索仅由工具调用触发
# --------------------------------------------------------------------------- #
class _FakeFastLLM:
    def __init__(self, chat_text="我记得呢"):
        self.chat_text = chat_text
        self.chat_calls = []

    async def chat(self, messages=None, stream=False, **kwargs):
        self.chat_calls.append((messages, kwargs))
        return type("Resp", (), {"content": self.chat_text})()


class TestVoiceFastMemory:
    def _session(self):
        return DualStreamSession(
            client_id="c1", agent_id="a1", request_id="r1",
            manager=FakeManager(), tts_service=FakeTTSService(),
        )

    def test_resolve_tools_returns_full_tools(self, monkeypatch):
        session = self._session()
        fake_tools = [
            {"function": {"name": "search_all_memories"}},
            {"function": {"name": "search_web"}},
            {"function": {"name": "call_assistant"}},
            {"function": {"name": "acp_send_message"}},
        ]
        monkeypatch.setattr("server.chat_helpers.get_tools_for_agent", lambda: fake_tools)
        tools = session._resolve_voice_tools()
        # 与普通模式一致：全量透传，不做记忆类过滤
        assert tools == fake_tools
        names = [t["function"]["name"] for t in tools]
        assert "search_all_memories" in names
        assert "search_web" in names
        assert "call_assistant" in names
        assert "acp_send_message" in names

    @pytest.mark.asyncio
    async def test_voice_stream_passthrough_without_tool_calls(self):
        session = self._session()
        llm = _FakeFastLLM()

        async def source():
            yield "你"
            yield "好"

        out = []
        async for c in session._voice_stream_with_tools(source(), [], llm, 0.7, 128):
            out.append(c)
        assert out == ["你", "好"]
        assert llm.chat_calls == []  # 无需二次生成

    @pytest.mark.asyncio
    async def test_voice_stream_executes_tool_and_regenerates(self, monkeypatch):
        session = self._session()
        executed = []

        def fake_execute(tool_calls, messages):
            executed.append(tool_calls)
            messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls})
            messages.append({"role": "tool", "tool_call_id": "c1", "name": "search_all_memories", "content": "[]"})

        monkeypatch.setattr("server.core.tools.builtin.execute_tool_calls", fake_execute)
        llm = _FakeFastLLM("刚刚聊过啊")

        async def source():
            yield {"type": "tool_calls", "tool_calls": [{"name": "search_all_memories"}]}

        out = []
        async for c in session._voice_stream_with_tools(source(), [], llm, 0.7, 128):
            out.append(c)
        assert executed, "应执行工具调用"
        assert executed[0][0]["name"] == "search_all_memories"
        assert llm.chat_calls, "工具后应二次生成文本"
        assert "刚刚聊过啊" in out