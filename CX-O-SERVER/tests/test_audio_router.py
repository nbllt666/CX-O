"""server.api.routers.audio 路由测试。

chdir 隔离 data/voice_refs 与 config + dependency_overrides 注入假 TTS/ASR 服务。
覆盖：
- config（GET 默认）
- files（GET 列表 / 上传 multipart / 获取 404/成功/路径遍历 400 / 删除 404/成功）
- TTS（synthesize 成功/空文本 / stream 缺文本 SSE/成功分块）
- ASR（multipart 成功 / json 成功 / 缺音频）

运行：python -m pytest tests/test_audio_router.py -v
"""
import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import get_asr_service, get_tts_service
from server.api.routers import audio as audio_router_mod


class FakeTTS:
    def __init__(self):
        self._speed = 1.0
        self._cross_fade_duration = 0.15

    async def synthesize(self, text, **kwargs):
        return b"\x00\x01RIFF"

    async def synthesize_stream(self, text, **kwargs):
        yield {"audio_data": b"abc", "text_segment": "你", "chunk_index": 0, "is_final": True}


class FakeASR:
    async def recognize(self, audio_data, language="auto"):
        return {"text": "你好", "language": language}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audio_router_mod, "VOICE_REFS_DIR", tmp_path / "data" / "voice_refs")
    tts = FakeTTS()
    asr = FakeASR()
    app = FastAPI()
    app.include_router(audio_router_mod.router)
    app.dependency_overrides[get_tts_service] = lambda: tts
    app.dependency_overrides[get_asr_service] = lambda: asr
    return TestClient(app, raise_server_exceptions=False), tts, asr


class TestAudioConfig:
    def test_default(self, client):
        c, tts, asr = client
        r = c.get("/audio/config")
        assert r.status_code == 200
        assert r.json()["engine"] == "f5"
        assert r.json()["speed"] == 1.0


class TestAudioFiles:
    def test_list_empty(self, client):
        c, tts, asr = client
        r = c.get("/audio/files")
        assert r.status_code == 200
        assert r.json()["files"] == []

    def test_upload_success(self, client, tmp_path):
        c, tts, asr = client
        r = c.post("/audio/upload", files={"file": ("a.wav", b"RIFF", "audio/wav")})
        assert r.status_code == 200
        assert r.json()["status"] == "success"
        assert (tmp_path / "data" / "voice_refs" / "a.wav").exists()

    def test_upload_bad_ext_400(self, client):
        c, tts, asr = client
        r = c.post("/audio/upload", files={"file": ("a.txt", b"x", "text/plain")})
        assert r.status_code == 400

    def test_upload_missing_file_400(self, client):
        c, tts, asr = client
        r = c.post("/audio/upload", files={})
        assert r.status_code == 400

    def test_get_file_404(self, client):
        c, tts, asr = client
        r = c.get("/audio/files/nope.wav")
        assert r.status_code == 404

    def test_get_file_success(self, client, tmp_path):
        c, tts, asr = client
        (tmp_path / "data" / "voice_refs").mkdir(parents=True)
        (tmp_path / "data" / "voice_refs" / "a.wav").write_bytes(b"RIFF")
        r = c.get("/audio/files/a.wav")
        assert r.status_code == 200
        assert r.content == b"RIFF"

    def test_get_file_traversal_404(self, client):
        # 含 / 的路径在路由层即被单段 {filename} 拒绝（404），handlet 的遍历防护不触发
        c, tts, asr = client
        r = c.get("/audio/files/..%2F..%2Fetc")
        assert r.status_code == 404


class TestValidateFilename:
    def test_empty_400(self, client):
        with pytest.raises(Exception):
            audio_router_mod._validate_filename("")

    def test_dotdot_400(self, client):
        with pytest.raises(Exception):
            audio_router_mod._validate_filename("../secret.wav")

    def test_absolute_400(self, client):
        with pytest.raises(Exception):
            audio_router_mod._validate_filename("C:/secret.wav")

    def test_valid_ok(self, client):
        assert audio_router_mod._validate_filename("a.wav") == "a.wav"

    def test_delete_404(self, client):
        c, tts, asr = client
        r = c.delete("/audio/files/nope.wav")
        assert r.status_code == 404

    def test_delete_success(self, client, tmp_path):
        c, tts, asr = client
        (tmp_path / "data" / "voice_refs").mkdir(parents=True)
        (tmp_path / "data" / "voice_refs" / "a.wav").write_bytes(b"RIFF")
        r = c.delete("/audio/files/a.wav")
        assert r.status_code == 200
        assert not (tmp_path / "data" / "voice_refs" / "a.wav").exists()


class TestTTSSynthesize:
    def test_success(self, client):
        c, tts, asr = client
        r = c.post("/tts/synthesize", json={"text": "你好"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert body["audio_data"] == base64.b64encode(b"\x00\x01RIFF").decode()

    def test_empty_text_error(self, client):
        c, tts, asr = client
        r = c.post("/tts/synthesize", json={"text": ""})
        assert r.status_code == 200
        assert r.json()["status"] == "error"


class TestTTSSynthesizeStream:
    def test_missing_text(self, client):
        c, tts, asr = client
        r = c.post("/tts/synthesize-stream", json={"text": ""})
        assert r.status_code == 200
        assert "缺少文本内容" in r.text

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

    def test_missing_audio_error(self, client):
        c, tts, asr = client
        r = c.post("/asr/speech-to-text", json={})
        assert r.status_code == 200
        assert r.json()["status"] == "error"