"""handlers/audio.py 声纹说话人字段透传测试（Task 7）。

覆盖 voice.partial payload 是否附带 speaker 字段——注册 / 未注册两态：
- 注册命中（speaker_registered=True）→ data 附带 speaker_id/speaker_name（=注册名），
  session 记录最近注册说话人；
- 未注册（伪名 spk_N）→ data 不带 speaker 字段，session 不记录伪名。

运行：python -m pytest tests/test_voice_audio_speaker.py -v
"""
import pytest

from server.handlers.audio import DualStreamSession, _registered_speaker_from
from server.protocol.actions import VoiceActions


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