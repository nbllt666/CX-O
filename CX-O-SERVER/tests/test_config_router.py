"""server.api.routers.config 路由测试。

monkeypatch.chdir 隔离 config/settings.json + monkeypatch server.config.get_settings /
Server.config.Settings / audio._load_tts_config / websocket.get_websocket_manager +
dependency_overrides 受保护依赖。覆盖：
- limits / 统一 config（GET/PUT 各 section）/ POST 别名
- sensevoice-streaming（GET 默认/POST 更新落盘）
- danmaku / firewall / firewall_v3 / vad config（缺省默认）
- live client status / disconnect
- config/audio、config/services、config/llm

运行：python -m pytest tests/test_config_router.py -v
"""
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
        self.weaviate = FakeBox(vector_size=1536, host="127.0.0.1", port=8082, embedded=False)
        self.embedding_provider = "ollama"
        self.embedding_model = "nomic"
        self.embedding_api_base = "http://127.0.0.1:8002"
        self.embedding_api_key = ""


class FakeModelConfig:
    """与 server.config.ModelConfig 字段兼容的假模型配置。"""

    def __init__(self, **kwargs):
        self.provider = "ollama"
        self.model = "qwen"
        self.host = "127.0.0.1"
        self.temperature = 0.7
        self.max_tokens = 4096
        self.timeout = 60
        self.top_p = None
        self.api_key = None
        self.__dict__.update(kwargs)


class FakeModels:
    def __init__(self):
        self.main = FakeModelConfig()
        self.summary = FakeModelConfig()
        self.memory = FakeModelConfig()
        self.defaults = {"summary": "main", "memory": "main"}


class FakeSettings:
    def __init__(self):
        self.config = FakeBox(
            limits=FakeBox(frontend=FakeBox(max_chars=1000)),
            memory=FakeMemory(),
            models=FakeModels(),
            llm=FakeBox(provider="ollama", model="qwen", host="127.0.0.1"),
            system=FakeBox(debug=False, log_level="INFO"),
            graph=FakeBox(enabled=True),
            vision_enhanced=FakeBox(enabled=False),
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
    # get_settings 在 config.py 模块顶层 from-import 绑定，须 patch 该模块引用
    monkeypatch.setattr(config_router_mod, "get_settings", lambda: settings)
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

    def test_get_llm_section_structure(self, client):
        c, settings = client
        r = c.get("/config")
        assert r.status_code == 200
        llm = r.json()["config"]["llm"]
        # 扩展后的 llm 节应包含 models/defaults/params 三个键
        assert set(llm["models"].keys()) == {"main", "summary", "memory"}
        assert llm["models"]["main"]["model"] == "qwen"
        assert llm["models"]["main"]["api_key"] == ""
        assert llm["defaults"] == {"summary": "main", "memory": "main"}
        assert llm["params"]["temperature"] == 0.7
        assert llm["params"]["maxTokens"] == 4096
        assert llm["params"]["topP"] is None
        assert llm["params"]["timeout"] == 60

    def test_get_vector_backend_embedded_mapping(self, client):
        c, settings = client
        settings.config.memory.weaviate.embedded = True
        r = c.get("/config")
        # weaviate + embedded=True 应映射为复合标识 weaviate_embedded
        assert r.json()["config"]["vector"]["backend"] == "weaviate_embedded"

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
                                   "data": {"danmaku": {"enabled": True}}})
        assert r.status_code == 200
        f = tmp_path / "config" / "settings.json"
        assert f.exists()

    def test_put_vector(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "vector", "data": {"backend": "weaviate"}})
        assert r.status_code == 200
        assert settings.config.memory.vector_backend == "weaviate"
        # 显式提交 backend=weaviate（独立部署）应关闭 embedded
        assert settings.config.memory.weaviate.embedded is False
        assert settings.saved == 1

    def test_put_vector_embedded_and_weaviate_fields(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "vector", "data": {
            "backend": "weaviate_embedded",
            "weaviate_host": "127.0.0.2",
            "weaviate_port": "8081",
        }})
        assert r.status_code == 200
        # weaviate_embedded 应拆解为 weaviate 后端 + embedded=True
        assert settings.config.memory.vector_backend == "weaviate"
        assert settings.config.memory.weaviate.embedded is True
        assert settings.config.memory.weaviate.host == "127.0.0.2"
        assert settings.config.memory.weaviate.port == 8081

    def test_put_llm(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "llm", "data": {"provider": "vllm"}})
        assert r.status_code == 200
        assert settings.config.llm.provider == "vllm"

    def test_put_llm_extended(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "llm", "data": {
            "models": {"main": {"model": "qwen2", "api_key": "sk-1"}},
            "model_defaults": {"summary": "memory"},
            "llm_params": {
                "temperature": 0.3,
                "maxTokens": 8192,
                "topP": 0.9,
                "timeout": 120,
            },
        }})
        assert r.status_code == 200
        # models entry：model 与 api_key 落位（空串归一化为 None 的反向场景）
        assert settings.config.models.main.model == "qwen2"
        assert settings.config.models.main.api_key == "sk-1"
        # model_defaults：仅更新出现的键，其余保留
        assert settings.config.models.defaults == {"summary": "memory", "memory": "main"}
        # llm_params：temperature/maxTokens 双落 llm 节与 models.main
        assert settings.config.llm.temperature == 0.3
        assert settings.config.models.main.temperature == 0.3
        assert settings.config.llm.max_tokens == 8192
        assert settings.config.models.main.max_tokens == 8192
        assert settings.config.models.main.top_p == 0.9
        assert settings.config.models.main.timeout == 120

    def test_put_llm_empty_api_key_normalized(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "llm", "data": {
            "models": {"main": {"api_key": ""}},
        }})
        assert r.status_code == 200
        # 空字符串 api_key 应归一化为 None
        assert settings.config.models.main.api_key is None

    def test_put_system(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "system", "data": {"debug": True}})
        assert r.status_code == 200
        assert settings.config.system.debug is True

    def test_put_graph(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "graph", "data": {"graph_enabled": False}})
        assert r.status_code == 200
        assert settings.config.graph.enabled is False
        assert settings.saved == 1

    def test_put_vision_enhanced(self, client):
        c, settings = client
        r = c.put("/config", json={"section": "vision_enhanced", "data": {"enabled": True}})
        assert r.status_code == 200
        assert settings.config.vision_enhanced.enabled is True
        assert settings.saved == 1

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

    def test_live_saved_value_read_back(self, client, tmp_path):
        # PUT /config live 保存 danmaku/firewall/vad 后，GET 应读回已保存值
        # （「已保存值叠加默认值」），而非恒返回默认。
        c, settings = client
        r = c.put("/config", json={"section": "live", "data": {
            "danmaku": {"websocket": {"max_connections": 42}},
        }})
        assert r.status_code == 200
        r = c.get("/danmaku/config")
        assert r.status_code == 200
        got = r.json()["config"]
        # 已保存值叠加默认值：嵌套键被保存值覆盖，其余保留默认
        assert got["websocket"]["max_connections"] == 42
        assert got["sources"]["bilibili"]["enabled"] is True


class TestLive:
    def test_client_status_disconnected(self, client):
        c, settings = client
        r = c.get("/live/client/status")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "disconnected"
        assert body["connected"] is False
        assert body["client_id"] is None

    def test_client_status_connected(self, client):
        c, settings = client
        # 向端点实际读取的 websocket manager 注入一个 type="live" 连接，
        # 模拟 /ws/live 端点建立真实直播连接的场景。
        from server.core.websocket.manager import WebSocketConnection

        class _FakeWebSocket:
            pass

        ws_manager = config_router_mod.get_websocket_manager()
        conn = WebSocketConnection(_FakeWebSocket(), "live-test-1", {"type": "live"})
        ws_manager.connections[conn.client_id] = conn
        try:
            r = c.get("/live/client/status")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "connected"
            assert body["connected"] is True
            assert body["client_id"] == conn.client_id
        finally:
            ws_manager.connections.pop(conn.client_id, None)

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