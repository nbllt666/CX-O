"""server.services.asr_service.receive_result 声纹字段解析测试（Task 4）。

覆盖两个状态：
- 服务端 WS JSON 携带 speaker_* 新字段 → 正确解析
- 旧容器不携带 speaker_* 字段（缺字段）→ 取默认值，向后兼容

运行：python -m pytest tests/test_asr_ws_speaker.py -v
"""
import json

import pytest

from server.services.asr_service import ASRService, StreamingASRResult


class FakeWS:
    """可注入 ASRService._ws 的假 WebSocket。"""

    def __init__(self):
        self.connected = True


@pytest.mark.asyncio
async def test_receive_result_parses_speaker_fields():
    """新字段齐全时逐字段解析。"""
    s = ASRService(mode="remote")
    s._ws = FakeWS()
    s._ws_recv_queue.put_nowait(json.dumps({
        "text": "你好", "is_final": True, "language": "zh",
        "speaker_id": "spk-001",
        "speaker_name": "阿明",
        "speaker_registered": True,
        "speaker_conf": 0.923,
    }))
    r = await s.receive_result(timeout=0)
    assert isinstance(r, StreamingASRResult)
    assert r.speaker_id == "spk-001"
    assert r.speaker_name == "阿明"
    assert r.speaker_registered is True
    assert r.speaker_conf == 0.923
    # 既有字段不受影响
    assert r.text == "你好"
    assert r.is_final is True


@pytest.mark.asyncio
async def test_receive_result_missing_speaker_fields_defaults():
    """旧容器缺 speaker_* 字段 → 取默认值，向后兼容。"""
    s = ASRService(mode="remote")
    s._ws = FakeWS()
    s._ws_recv_queue.put_nowait(json.dumps({"text": "你好", "is_final": False}))
    r = await s.receive_result(timeout=0)
    assert isinstance(r, StreamingASRResult)
    assert r.speaker_id == ""
    assert r.speaker_name == ""
    assert r.speaker_registered is False
    assert r.speaker_conf == 0.0


@pytest.mark.asyncio
async def test_receive_result_speaker_name_fallback_to_id():
    """未注册且提供 speaker_id 时，speaker_name 回退为空串；注册时回退为 speaker_id。"""
    s = ASRService(mode="remote")
    s._ws = FakeWS()
    # 未提供 speaker_name，但 registered=True → name 回退为 id
    s._ws_recv_queue.put_nowait(json.dumps({
        "text": "hi", "speaker_id": "spk-9", "speaker_registered": True,
    }))
    r = await s.receive_result(timeout=0)
    assert r.speaker_registered is True
    assert r.speaker_name == "spk-9"

    s2 = ASRService(mode="remote")
    s2._ws = FakeWS()
    # 未提供 speaker_name 且未注册 → name 为空串
    s2._ws_recv_queue.put_nowait(json.dumps({
        "text": "hi", "speaker_id": "spk-9", "speaker_registered": False,
    }))
    r2 = await s2.receive_result(timeout=0)
    assert r2.speaker_name == ""


@pytest.mark.asyncio
async def test_receive_result_speaker_conf_missing_uses_zero():
    """缺 speaker_conf 时 → 0.0（旧容器兼容）。"""
    s = ASRService(mode="remote")
    s._ws = FakeWS()
    s._ws_recv_queue.put_nowait(json.dumps({"text": "hi", "speaker_id": "x"}))
    r = await s.receive_result(timeout=0)
    assert r.speaker_conf == 0.0