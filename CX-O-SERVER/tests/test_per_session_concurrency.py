"""
per-session 并发化改造回归测试（地基改造：多 client_id 实时语音会话并行不串扰）。

覆盖三类核心隔离：
1. VAD per-client：两个会话各自 VAD 状态机不干扰（A 说话 ≠ B 说话）
2. ASR per-client 流式结果归属：A/B 各自上行各自收结果，不混插
3. 打断模块 per-client：A 播 TTS 不影响 B 的打断判定

运行：python -m pytest tests/test_per_session_concurrency.py -v
"""
import struct
import json

import pytest

from server.services import asr_service
from server.services.asr_service import ASRService
from server.services.asr_interrupt import get_asr_interrupt_module
from server.services.agent_interrupt_user import get_agent_interrupt_module
from server.services.vad_processor import (
    get_vad_processor,
    get_audio_stream_processor,
    _client_vad_processors,
    _client_audio_stream_processors,
)
from server.handlers.audio import set_tts_playing, _tts_playing_clients


class FakeWS:
    """可注入 ASR 服务端点的假 WebSocket（记录发送内容）。"""

    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


@pytest.fixture(autouse=True)
def _clean_registries():
    """清理 per-client 注册表，避免跨测试污染。"""
    yield
    _client_vad_processors.clear()
    _client_audio_stream_processors.clear()
    from server.services.asr_interrupt import _asr_interrupt_instances
    from server.services.agent_interrupt_user import _agent_interrupt_instances
    _asr_interrupt_instances.clear()
    _agent_interrupt_instances.clear()
    _tts_playing_clients.clear()
    asr_service._asr_service = None
    # 清理 ASRService per-client 流式会话（走默认单例）
    global _asr_instances
    for s in _asr_instances:
        s._stream_sessions.clear()


_asr_instances = []


def _samples_energy(amplitude: int, n: int = 480) -> bytes:
    """构造能量为 amplitude^2 的 PCM 音频帧（16bit LE mono）。"""
    return struct.pack(f"<{n}h", *([amplitude] * n))


def _make_asr() -> ASRService:
    s = ASRService(mode="remote")
    s._initialized = True
    _asr_instances.append(s)
    return s


# ================================================================ T1: VAD per-client
class TestPerClientVAD:
    def test_vad_state_machine_is_isolated(self):
        vad_a = get_vad_processor("client-A")
        vad_b = get_vad_processor("client-B")
        # 各客户端用独立实例
        assert vad_a is not vad_b

        for vad in (vad_a, vad_b):
            vad.set_config({"mode": "energy", "energy_threshold": 500, "sample_rate": 16000})

        # 高能量帧（PCM 1000^2）喂给 A → A 说话，B 不干扰
        vad_a.process_audio(_samples_energy(1000, n=480))
        assert vad_a.is_speaking is True
        assert vad_b.is_speaking is False  # B 状态不受 A 影响

        # B 仍可独立进入说话
        vad_b.process_audio(_samples_energy(1000, n=480))
        assert vad_b.is_speaking is True
        assert vad_a.is_speaking is True  # A 保持说话，互不覆盖

    def test_audio_stream_processor_is_isolated(self):
        sp_a = get_audio_stream_processor("client-A")
        sp_b = get_audio_stream_processor("client-B")
        assert sp_a is not sp_b
        # 各自 VAD 内嵌实例亦不同
        assert sp_a.vad is not sp_b.vad


# ================================================================ T2: ASR per-client 归属
class TestPerClientASR:
    @pytest.mark.asyncio
    async def test_results_attributed_per_client(self):
        s = _make_asr()
        st_a = s._stream_accessor("A")
        st_b = s._stream_accessor("B")
        st_a.ws = FakeWS()
        st_b.ws = FakeWS()
        # 各客户端独立接收队列注入各自结果
        st_a.recv_queue.put_nowait(json.dumps({"text": "A说的话", "is_final": True}))
        st_b.recv_queue.put_nowait(json.dumps({"text": "B说的话", "is_final": False}))

        ra = await s.receive_result(timeout=0, client_id="A")
        rb = await s.receive_result(timeout=0, client_id="B")

        assert ra.text == "A说的话"
        assert ra.is_final is True
        assert rb.text == "B说的话"
        assert rb.is_final is False
        # 默认会话取不到任何 A/B 的结果（独立队列，未混插）
        assert await s.receive_result(timeout=0) is None

    @pytest.mark.asyncio
    async def test_send_audio_chunk_goes_to_own_ws(self):
        s = _make_asr()
        st_a = s._stream_accessor("A")
        st_b = s._stream_accessor("B")
        st_a.ws = FakeWS()
        st_b.ws = FakeWS()

        assert await s.send_audio_chunk(b"\x00", client_id="A") is True
        assert await s.send_audio_chunk(b"\x01", client_id="B") is True

        assert st_a.ws.sent == [b"\x00"]
        assert st_b.ws.sent == [b"\x01"]

    @pytest.mark.asyncio
    async def test_reset_only_clears_own_queue(self):
        s = _make_asr()
        st_a = s._stream_accessor("A")
        st_b = s._stream_accessor("B")
        st_a.recv_queue.put_nowait("m-a")
        st_b.recv_queue.put_nowait("m-b")

        await s.reset(client_id="A")
        assert st_a.recv_queue.empty()
        assert not st_b.recv_queue.empty()  # B 队列不受影响

    @pytest.mark.asyncio
    async def test_release_streaming_session_only_removes_target(self):
        s = _make_asr()
        s._stream_accessor("A")
        s._stream_accessor("B")
        assert "A" in s._stream_sessions and "B" in s._stream_sessions

        await s.release_streaming_session("A")
        assert "A" not in s._stream_sessions
        assert "B" in s._stream_sessions


# ================================================================ T3: 打断模块 per-client
class TestPerClientInterrupt:
    @pytest.mark.asyncio
    async def test_asr_interrupt_tts_playing_isolated(self):
        mod_a = get_asr_interrupt_module("client-A")
        mod_b = get_asr_interrupt_module("client-B")
        assert mod_a is not mod_b

        mod_a.set_tts_playing(True)
        mod_b.set_tts_playing(False)
        assert mod_a._tts_playing is True
        assert mod_b._tts_playing is False

        # B 的 TTS 未播放 → 打断判定直接 IGNORE（不触发 LLM）
        decision, triggered = await mod_b.on_asr_result("你好")
        assert decision == "IGNORE"
        assert triggered is False

    @pytest.mark.asyncio
    async def test_set_tts_playing_affects_only_own_client(self):
        mod_a = get_asr_interrupt_module("client-A")
        mod_b = get_asr_interrupt_module("client-B")

        await set_tts_playing("client-A", True)
        assert mod_a._tts_playing is True
        assert mod_b._tts_playing is False  # A 播 TTS 不影响 B 打断判定

        await set_tts_playing("client-B", True)
        assert mod_b._tts_playing is True
        assert mod_a._tts_playing is True

        await set_tts_playing("client-A", False)
        await set_tts_playing("client-B", False)

    def test_agent_interrupt_speech_state_isolated(self):
        agm_a = get_agent_interrupt_module("client-A")
        agm_b = get_agent_interrupt_module("client-B")
        assert agm_a is not agm_b

        agm_a.on_user_speech_start()
        assert agm_a.is_user_speaking is True
        assert agm_b.is_user_speaking is False  # B 的说话时序不受 A 影响

        agm_b.on_user_speech_start()
        assert agm_a.is_user_speaking is True
        assert agm_b.is_user_speaking is True