"""handlers/audio.py 声纹说话人字段透传测试（Task 7）。

覆盖 voice.partial payload 是否附带 speaker 字段——注册 / 未注册两态：
- 注册命中（speaker_registered=True）→ data 附带 speaker_id/speaker_name（=注册名），
  session 记录最近注册说话人；
- 未注册（伪名 spk_N）→ data 不带 speaker 字段，session 不记录伪名。

运行：python -m pytest tests/test_voice_audio_speaker.py -v
"""
import struct

import pytest

from server.handlers.audio import DualStreamSession, _registered_speaker_from, _speaker_label_from
from server.protocol.actions import VoiceActions
from server.services.asr_service import StreamingASRResult
from server.services.vad_processor import AudioStreamProcessor


class FakeManager:
    """最小 fake manager：仅采集发出的消息。"""

    def __init__(self):
        self.sent = []

    async def send_message(self, client_id, message):
        self.sent.append((client_id, message))


class FakeTTSService:
    """最小 fake TTS：双流式会话构造所需，本测试不触发其方法。"""

    async def synthesize_stream_fine(self, *args, **kwargs):
        yield {"is_final": True}


def _session():
    mgr = FakeManager()
    session = DualStreamSession(
        client_id="c1", agent_id="a1", request_id="r1",
        manager=mgr, tts_service=FakeTTSService(),
    )
    # 跳过首帧延续性确认与 LLM pipeline 触发，仅观察 partial 转发
    session._partial_confirmed = True
    session._has_triggered_this_utterance = True
    return session, mgr


def _partial_payloads(mgr):
    return [
        m for (_cid, m) in mgr.sent
        if m.get("type") == VoiceActions.PARTIAL
    ]


@pytest.mark.asyncio
async def test_partial_registered_speaker_attached():
    """注册命中：voice.partial data 附带 speaker_id/speaker_name，session 记录说话人。"""
    session, mgr = _session()
    await session.on_partial_result({
        "text": "你好", "is_final": False,
        "speaker_id": "阿明", "speaker_name": "阿明",
        "speaker_registered": True, "speaker_conf": 0.9,
    })
    payloads = _partial_payloads(mgr)
    assert payloads, "应有 voice.partial 消息"
    data = payloads[0]["data"]
    assert data["speaker_id"] == "阿明"
    assert data["speaker_name"] == "阿明"
    assert session._last_speaker_name == "阿明"


@pytest.mark.asyncio
async def test_partial_unregistered_speaker_omitted():
    """未注册（伪名 spk_N）：voice.partial data 不带 speaker 字段，session 不记录伪名。"""
    session, mgr = _session()
    await session.on_partial_result({
        "text": "你好", "is_final": False,
        "speaker_id": "spk_3", "speaker_name": "",
        "speaker_registered": False, "speaker_conf": 0.0,
    })
    payloads = _partial_payloads(mgr)
    assert payloads, "应有 voice.partial 消息"
    data = payloads[0]["data"]
    assert "speaker_id" not in data
    assert "speaker_name" not in data
    assert session._last_speaker_name == ""


@pytest.mark.asyncio
async def test_final_registered_speaker_attached():
    """注册命中且推送 final：voice.partial(is_final=True) 同样附带 speaker 字段。"""
    session, mgr = _session()
    await session.on_final_result({
        "text": "你好", "is_final": True,
        "speaker_id": "阿明", "speaker_name": "阿明",
        "speaker_registered": True, "speaker_conf": 0.92,
    })
    payloads = _partial_payloads(mgr)
    assert payloads
    data = payloads[0]["data"]
    assert data["is_final"] is True
    assert data["speaker_name"] == "阿明"


@pytest.mark.asyncio
async def test_default_behavior_without_speaker_fields():
    """旧容器缺 speaker_* 字段：partial 不带 speaker 字段，向后兼容。"""
    session, mgr = _session()
    await session.on_partial_result({"text": "你好", "is_final": False})
    payloads = _partial_payloads(mgr)
    assert payloads
    data = payloads[0]["data"]
    assert "speaker_id" not in data
    assert "speaker_name" not in data
    assert session._last_speaker_name == ""


def test_registered_speaker_from_result():
    """_registered_speaker_from：仅注册命中取非空名；未注册/缺字段返回空串。"""
    assert _registered_speaker_from({
        "speaker_registered": True, "speaker_name": "阿明",
    }) == "阿明"
    assert _registered_speaker_from({
        "speaker_registered": True, "speaker_id": "spk-9", "speaker_name": "",
    }) == "spk-9"
    assert _registered_speaker_from(
        {"speaker_registered": True, "speaker_id": "spk_3", "speaker_name": ""}
    ) != ""
    assert _registered_speaker_from({
        "speaker_registered": False, "speaker_id": "spk_3", "speaker_name": "",
    }) == ""
    assert _registered_speaker_from({}) == ""
    assert _registered_speaker_from(None) == ""


def test_registered_speaker_from_never_exposes_pseudonym_fallback_ids():
    """注册名下即使回退到 spk_N 形态 id，也仅当 registered=True 才放行（伪名由容器控制）。"""
    # 这里语义：registered=True 且容器直接返回名字；spk_N 伪名只出现在 registered=False
    assert _registered_speaker_from({
        "speaker_registered": True, "speaker_id": "spk_2", "speaker_name": "铁柱",
    }) == "铁柱"
    assert _registered_speaker_from({
        "speaker_registered": False, "speaker_id": "spk_2", "speaker_name": "",
    }) == ""


# ---- 说话人标签外发（Task） ----


def _speaker_energy_samples(amplitude: int, n: int = 480) -> bytes:
    """构造能量为 amplitude^2 的 PCM 音频帧（16bit LE mono）。"""
    return struct.pack(f"<{n}h", *([amplitude] * n))


_HIGH_SAMPLES = _speaker_energy_samples(1000)


class _FakeStream:
    """返回带 speaker_status 字段的流式 ASR 假客户端。"""

    def __init__(self, result):
        self.result = result
        self.sent = 0

    async def send_audio_chunk(self, data, is_last=False, client_id=None):
        self.sent += 1
        return True

    async def receive_result(self, timeout=0, client_id=None):
        return self.result

    async def reset(self, client_id=None):
        pass


def test_speaker_label_from():
    """_speaker_label_from：pending → '识别中'；注册命中 → 注册名；其它 → ''。"""
    # pending 态（无论文本是否为空）→ '识别中'
    assert _speaker_label_from({"speaker_status": "pending", "text": "你好"}) == "识别中"
    assert _speaker_label_from({"speaker_status": "pending", "text": ""}) == "识别中"
    # 注册命中 → 注册名（受控 fallback 到 speaker_id）
    assert _speaker_label_from({
        "speaker_status": "ready", "speaker_registered": True, "speaker_name": "阿明",
    }) == "阿明"
    assert _speaker_label_from({
        "speaker_status": "ready", "speaker_registered": True, "speaker_id": "spk-9",
        "speaker_name": "",
    }) == "spk-9"
    # 未注册 / 缺字段 → ''
    assert _speaker_label_from({
        "speaker_status": "ready", "speaker_registered": False, "speaker_name": "",
    }) == ""
    assert _speaker_label_from({"speaker_registered": False}) == ""  # 缺 speaker_status 默认 ready
    assert _speaker_label_from({}) == ""
    assert _speaker_label_from(None) == ""


@pytest.mark.asyncio
async def test_partial_pending_speaker_label_identifying():
    """pending 态：voice.partial data 附带 speaker_label='识别中'（speaker 字段保持为空）。"""
    session, mgr = _session()
    await session.on_partial_result({
        "text": "你好", "is_final": False,
        "speaker_status": "pending",
        "speaker_id": "", "speaker_name": "",
        "speaker_registered": False, "speaker_conf": 0.0,
    })
    payloads = _partial_payloads(mgr)
    assert payloads, "应有 voice.partial 消息"
    data = payloads[0]["data"]
    assert data["speaker_label"] == "识别中"
    # pending 态不归属名字：speaker_id/speaker_name 保持缺席
    assert "speaker_id" not in data
    assert "speaker_name" not in data


@pytest.mark.asyncio
async def test_empty_text_supplement_does_not_trigger_prefill():
    """spk 补充消息（text='' is_final=False speaker_status ready + speaker_id）：
    不应触发 prefill 回调 —— 仅用于更新说话人，不驱动无意义 LLM Speculative Prefill。
    """
    proc = AudioStreamProcessor(client_id="spk-empty")
    proc.set_config({"vad": {"mode": "energy", "energy_threshold": 500, "sample_rate": 16000}})
    called = []
    proc.set_callbacks(on_partial_result=lambda asr_result: called.append(asr_result))
    fake = _FakeStream(StreamingASRResult(
        text="", is_final=False,
        speaker_status="ready", speaker_id="spk-1", speaker_name="阿明",
        speaker_registered=True, speaker_conf=0.9,
    ))
    proc.set_asr_client(fake)

    await proc.process_audio_chunk(_HIGH_SAMPLES)
    assert called == [], "空文本 spk 补充消息不应触发 prefill 回调"


@pytest.mark.asyncio
async def test_nonempty_text_triggers_prefill_control():
    """对照：非空文本 partial 仍应触发 prefill，且透传 speaker_status（验证测试有效性与透传）。"""
    proc = AudioStreamProcessor(client_id="spk-text")
    proc.set_config({"vad": {"mode": "energy", "energy_threshold": 500, "sample_rate": 16000}})
    called = []
    proc.set_callbacks(on_partial_result=lambda asr_result: called.append(asr_result))
    fake = _FakeStream(StreamingASRResult(
        text="你好", is_final=False, speaker_status="pending",
    ))
    proc.set_asr_client(fake)

    await proc.process_audio_chunk(_HIGH_SAMPLES)
    assert called, "非空文本 partial 应触发 prefill 回调"
    assert called[0]["speaker_status"] == "pending"