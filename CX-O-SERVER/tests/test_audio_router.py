"""server.api.routers.audio 路由测试。

chdir 隔离 config + dependency_overrides 注入假 TTS/ASR 服务。
覆盖：
- config（GET 默认）
- TTS（synthesize 成功/空文本400/下游失败502 / stream 缺文本 SSE/成功分块）
- ASR（multipart 成功 / json 成功 / 缺音频400 / 下游失败502）

运行：python -m pytest tests/test_audio_router.py -v
"""
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import get_asr_service, get_tts_service
from server.api.routers import audio as audio_router_mod
from server.services.tts_service import TTSServiceUnavailableError


class FakeTTS:
    def __init__(self):
        self._speed = 1.0
        self._cross_fade_duration = 0.15

    def _ensure_qwen3_ready(self):
        pass

    async def synthesize(self, text, **kwargs):
        return b"\x00\x01RIFF"

    async def synthesize_stream(self, text, **kwargs):
        yield {"audio_data": b"abc", "text_segment": "你", "chunk_index": 0, "is_final": True}


class FakeBrokenTTS(FakeTTS):
    """H10/M：模拟 Qwen3 未启用的 TTSService——守卫生效后合成入口抛出明确异常。"""

    def _ensure_qwen3_ready(self):
        raise TTSServiceUnavailableError("Qwen3 TTS 未启用或 Provider 缺失")

    async def synthesize(self, text, **kwargs):
        self._ensure_qwen3_ready()
        return b""

    async def synthesize_stream(self, text, **kwargs):
        self._ensure_qwen3_ready()
        yield {}


class FakeASR:
    async def recognize(self, audio_data, language="auto"):
        return {"text": "你好", "language": language}


class FakeBrokenASR:
    async def recognize(self, audio_data, language="auto"):
        raise RuntimeError("downstream asr unavailable")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    tts = FakeTTS()
    asr = FakeASR()
    app = FastAPI()
    app.include_router(audio_router_mod.router)
    app.dependency_overrides[get_tts_service] = lambda: tts
    app.dependency_overrides[get_asr_service] = lambda: asr
    return TestClient(app, raise_server_exceptions=False), tts, asr


@pytest.fixture
def broken_client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(audio_router_mod.router)
    app.dependency_overrides[get_tts_service] = lambda: FakeBrokenTTS()
    app.dependency_overrides[get_asr_service] = lambda: FakeBrokenASR()
    return TestClient(app, raise_server_exceptions=False)


class TestAudioConfig:
    def test_default(self, client):
        c, tts, asr = client
        r = c.get("/audio/config")
        assert r.status_code == 200
        assert r.json()["engine"] == "qwen3"
        assert r.json()["speed"] == 1.0


class TestTTSSynthesize:
    def test_success(self, client):
        c, tts, asr = client
        r = c.post("/tts/synthesize", json={"text": "你好"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["audio_data"] == base64.b64encode(b"\x00\x01RIFF").decode()

    def test_empty_text_returns_400(self, client):
        # M：参数缺失 → HTTPException 400（旧实现返回 200 + status=error）
        c, tts, asr = client
        r = c.post("/tts/synthesize", json={"text": ""})
        assert r.status_code == 400

    def test_unavailable_provider_returns_502(self, broken_client):
        # H10：Qwen3 未启用 → 明确异常映射 HTTP 502（不再 AttributeError 假成功）
        c = broken_client
        r = c.post("/tts/synthesize", json={"text": "你好"})
        assert r.status_code == 502


class TestTTSSynthesizeStream:
    def test_missing_text(self, client):
        # SSE 错误流保持 200（前端按 SSE 协议读 event）
        c, tts, asr = client
        r = c.post("/tts/synthesize-stream", json={"text": ""})
        assert r.status_code == 200
        assert "缺少文本内容" in r.text

    def test_unavailable_provider_sse_error(self, broken_client):
        # H10：未启用 Provider 时流式入口在初始化阶段即返回 error 事件，不进入合成
        c = broken_client
        r = c.post("/tts/synthesize-stream", json={"text": "你好"})
        assert r.status_code == 200
        assert "TTS 服务不可用" in r.text

    def test_success(self, client):
        c, tts, asr = client
        r = c.post("/tts/synthesize-stream", json={"text": "你好"})
        assert r.status_code == 200
        assert "data:" in r.text
        assert "chunk" in r.text


class TestASR:
    def test_multipart_success(self, client):
        c, tts, asr = client
        r = c.post("/asr/speech-to-text", files={"file": ("a.wav", b"RIFF", "audio/wav")})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert r.json()["text"] == "你好"

    def test_json_success(self, client):
        c, tts, asr = client
        audio = base64.b64encode(b"RIFF").decode()
        r = c.post("/asr/speech-to-text", json={"audio": audio, "language": "zh"})
        assert r.status_code == 200
        assert r.json()["text"] == "你好"
        assert r.json()["language"] == "zh"

    def test_missing_audio_returns_400(self, client):
        # M：参数缺失 → HTTPException 400（旧实现返回 200 + status=error）
        c, tts, asr = client
        r = c.post("/asr/speech-to-text", json={})
        assert r.status_code == 400

    def test_multipart_missing_file_returns_400(self, client):
        # M：multipart 无 file 字段 → 400
        c, tts, asr = client
        r = c.post(
            "/asr/speech-to-text",
            content=b"",
            headers={"Content-Type": "multipart/form-data; boundary=x"},
        )
        assert r.status_code in (400, 422)  # FastAPI 对残缺 multipart 可能先拦为 422

    def test_downstream_failure_returns_502(self, broken_client):
        # M：ASR 下游异常 → 502（旧行为 200 + status=error 假成功）
        c = broken_client
        audio = base64.b64encode(b"RIFF").decode()
        r = c.post("/asr/speech-to-text", json={"audio": audio})
        assert r.status_code == 502
