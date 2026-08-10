"""server.api.routers.config 路由测试。

monkeypatch.chdir 隔离 config/settings.json + monkeypatch server.config.get_settings /
Server.config.Settings / audio._load_tts_config / websocket.get_websocket_manager +
dependency_overrides 受保护依赖。覆盖：
- limits / 统一 config（GET/PUT 各 section）/ POST 别名
- sensevoice-streaming / adaptive-polling（GET 默认/POST 更新落盘）
- danmaku / firewall / firewall_v3 / vad config（缺省默认）
- live client status / disconnect
- config/audio、config/services、config/llm

运行：python -m pytest tests/test_config_router.py -v
"""
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import config as config_router_mod
from server.api.routers import audio as audio_router_mod
from server.api.routers.admin import verify_admin_api_key
from server.core import websocket as websocket_core


class FakeBox:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def model_dump(self):
        return self.__dict__.copy()


class FakeMemory:
    def __init__(self):
        self.vector_backend = "chroma"
        self.weaviate = FakeBox(vector_size=1536, host="127.0.0.1", port=8082)
        self.embedding_provider = "ollama"
        self.embedding_model = "nomic"
        self.embedding_api_base = "http://127.0.0.1:8002"
        self.embedding_api_key = ""


class FakeSettings:
    def __init__(self):
        self.config = FakeBox(
            limits=FakeBox(frontend=FakeBox(max_chars=1000)),
            memory=FakeMemory(),
            llm=FakeBox(provider="ollama", model="qwen", host="127.0.0.1"),
            system=FakeBox(debug=False, log_level="INFO"),
        )
        self.saved = 0

    def save_config(self):
        self.saved += 1


class FakeWSManager:
    async def disconnect(self, client_id):
        return None


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config_router_mod, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(audio_router_mod, "_PROJECT_ROOT", tmp_path)
    settings = FakeSettings()
    monkeypatch.setattr("server.config.get_settings", lambda: settings)
    # Settings 在 config.py 模块顶层 from-import 绑定，须 patch 该模块引用
    monkeypatch.setattr(config_router_mod, "Settings", lambda: settings)
    monkeypatch.setattr(audio_router_mod, "_load_tts_config",
                        lambda: {"ref_audio_path": "", "speed": 1.0})
    monkeypatch.setattr(websocket_core, "get_websocket_manager", lambda: FakeWSManager())

    app = FastAPI()
    app.include_router(config_router_mod.router)
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app, raise_server_exceptions=False), settings


class TestLimits:
    def test_success(self, client):
        c, settings = client
        r = c.get("/config/limits")
        assert r.status_code == 200
        assert r.json()["max_chars"] == 1000


class TestUnifiedConfig:
    def test_get(self, client):
        c, settings = client
        r = c.get("/config")
        assert r.status_code == 200
        cfg = r.json()["config"]
        assert cfg["audio"]["speed"] == 1.0
        assert cfg["vector"]["backend"] == "chroma"
        assert cfg["llm"]["provider"] == "ollama"
        assert cfg["system"]["debug"] is False

    def test_put_missing_section_400(self, client):
        c, settings = client
        r = c.put("/config", json={"data": {}})
        assert r.status_code == 400

    def test_put_unknown_section_400(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "nope", "data": {}})
        assert r.status_code == 400

    def test_put_audio(self, client, tmp_path):
        c, settings = client
        r = c.put("/config", json={"section": "audio", "data": {"speed": 1.5}})
        assert r.status_code == 200
        f = tmp_path / "config" / "settings.json"
        assert f.exists()
        assert f.read_text(encoding="utf-8").find("1.5") != -1

    def test_put_live(self, client, tmp_path):
        c, settings = client
        r = c.put("/config", json={"section": "live",
                                   "data": {"danmaku": {"enabled": True},
                                            "adaptive_polling": {"enabled": False}}})
        assert r.status_code == 200
        f = tmp_path / "config" / "settings.json"
        assert f.exists()

    def test_put_vector(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "vector", "data": {"backend": "weaviate"}})
        assert r.status_code == 200
        assert settings.config.memory.vector_backend == "weaviate"
        assert settings.saved == 1

    def test_put_llm(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "llm", "data": {"provider": "vllm"}})
        assert r.status_code == 200
        assert settings.config.llm.provider == "vllm"

    def test_put_system(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "system", "data": {"debug": True}})
        assert r.status_code == 200
        assert settings.config.system.debug is True

    def test_put_requires_admin(self, client):
        c, settings = client
        c.app.dependency_overrides[verify_admin_api_key] = lambda: (_ for _ in ()).throw(Exception("unauth"))
        r = c.put("/config", json={"section": "system", "data": {}})
        assert r.status_code == 500

    def test_post_alias(self, client):
        c, settings = client
        r = c.post("/config", json={"section": "system", "data": {"log_level": "DEBUG"}})
        assert r.status_code == 200


class TestSenseVoiceStreaming:
    def test_get_default(self, client):
        c, settings = client
        r = c.get("/config/sensevoice-streaming")
        assert r.status_code == 200
        assert r.json()["config"]["chunk_size"] == 1024

    def test_post_update(self, client, tmp_path):
        c, settings = client
        r = c.post("/config/sensevoice-streaming", json={"chunk_size": 2048, "hop_size": 256})
        assert r.status_code == 200
        assert (tmp_path / "config" / "settings.json").exists()


class TestAdaptivePolling:
    def test_get_default(self, client):
        c, settings = client
        r = c.get("/config/adaptive-polling")
        assert r.status_code == 200
        assert r.json()["config"]["enabled"] is True

    def test_post_update(self, client, tmp_path):
        c, settings = client
        r = c.post("/config/adaptive-polling", json={"enabled": False, "max_interval_ms": 800})
        assert r.status_code == 200
        assert (tmp_path / "config" / "settings.json").exists()


class TestYamlConfigs:
    def test_danmaku_default(self, client):
        c, settings = client
        r = c.get("/danmaku/config")
        assert r.status_code == 200
        assert r.json()["config"]["sources"]["bilibili"]["room_id"] == "12345678"

    def test_firewall_default(self, client):
        c, settings = client
        r = c.get("/firewall/config")
        assert r.json()["config"]["llm"]["default_model"] == "qwen2.5:latest"

    def test_firewall_v3_default(self, client):
        c, settings = client
        r = c.get("/firewall/v3/config")
        assert r.json()["config"]["interrupt"]["enabled"] is True

    def test_vad_default(self, client):
        c, settings = client
        r = c.get("/vad/config")
        assert r.json()["config"]["vad"]["mode"] == "webrtc"


class TestLive:
    def test_client_status(self, client):
        c, settings = client
        r = c.get("/live/client/status")
        assert r.status_code == 200
        assert r.json()["config"]["status"] == "disabled"

    def test_disconnect(self, client):
        c, settings = client
        r = c.post("/live/client/c1/disconnect")
        assert r.status_code == 200
        assert r.json()["message"] == "客户端 c1 已断开"


class TestAudioConfig:
    def test_get(self, client):
        c, settings = client
        r = c.get("/config/audio")
        assert r.status_code == 200
        assert r.json()["config"]["speed"] == 1.0

    def test_post(self, client, tmp_path):
        c, settings = client
        r = c.post("/config/audio", json={"speed": 2.0})
        assert r.status_code == 200
        assert (tmp_path / "config" / "settings.json").exists()


class TestServicesConfig:
    def test_get_empty(self, client):
        c, settings = client
        r = c.get("/config/services")
        assert r.status_code == 200
        assert r.json()["config"] == {}

    def test_post(self, client, tmp_path):
        c, settings = client
        r = c.post("/config/services", json={"danmaku": {"x": 1}})
        assert r.status_code == 200
        assert (tmp_path / "config" / "settings.json").exists()


class TestLLMConfig:
    def test_post(self, client):
        c, settings = client
        r = c.post("/config/llm", json={"provider": "openai", "model": "gpt4"})
        assert r.status_code == 200
        assert settings.config.llm.provider == "openai"
        assert settings.config.llm.model == "gpt4"