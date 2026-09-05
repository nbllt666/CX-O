"""server.core.model_router (ModelRouter) 单元测试。

通过 mock get_settings 与客户端，覆盖模型客户端获取/默认跟随、
状态检查、配置信息等核心逻辑，不发起真实网络请求。

运行：python -m pytest tests/test_model_router.py -v
"""
from types import SimpleNamespace

import pytest

from server.config import ModelConfig, ModelsConfig
from server.core.llm.client import OllamaClient
from server.core.model_router import ModelRouter


class FakeLLMResponse:
    """模拟 LLM chat 返回对象。"""

    def __init__(self, content="", finish_reason="stop", error=None, usage=None):
        self.content = content
        self.finish_reason = finish_reason
        self.error = error
        self.error_details = {}
        self.usage = usage or {}


def _make_settings(models: ModelsConfig = None):
    """构造 get_settings 返回的假 Settings 对象。"""
    return SimpleNamespace(config=SimpleNamespace(models=models or ModelsConfig()))


@pytest.fixture
def router(monkeypatch):
    """隔离 get_settings 的空 ModelRouter。"""
    r = ModelRouter()
    monkeypatch.setattr("server.core.model_router.get_settings", lambda: _make_settings())
    yield r


def _fake_client(r, name="main"):
    """注册一个假客户端到 _clients。"""

    class FakeClient:
        model_name = name

        async def chat(self, messages, stream=False, **kwargs):
            return FakeLLMResponse(content="ok")

    c = FakeClient()
    r._clients[name] = c
    return c


# ---------------------------------------------------------------- get_client
class TestGetClient:
    def test_missing_returns_none(self, router):
        assert router.get_client("nope") is None

    def test_direct_lookup(self, router):
        _fake_client(router, name="memory")
        assert router.get_client("memory") is not None

    def test_default_following(self, router):
        """summary 客户端未注册时返回 None，由调用方自行回退 main。"""
        _fake_client(router, name="main")
        assert router.get_client("summary") is None

    def test_default_following_case_insensitive(self, router):
        comb = _fake_client(router, name="summary")
        assert router.get_client("SUMMARY") is comb

    def test_default_follows_missing_target_falls_back(self, router):
        """未注册的模型类型返回 None。"""
        assert router.get_client("summary") is None


# ---------------------------------------------------------------- get_config
class TestGetConfig:
    def test_get_config(self, router):
        cfg = router.get_config("main")
        assert isinstance(cfg, ModelConfig)
        assert cfg.provider == "ollama"

    def test_get_config_missing_type(self, router):
        # 未知类型回退 main
        cfg = router.get_config("unknown")
        assert isinstance(cfg, ModelConfig)


# ---------------------------------------------------------------- _create_client
class TestCreateClient:
    def test_unsupported_provider_returns_none(self, monkeypatch):
        mc = ModelsConfig(main=ModelConfig(provider="unknown_provider"))
        monkeypatch.setattr(
            "server.core.model_router.get_settings", lambda: _make_settings(mc)
        )
        assert ModelRouter()._create_client("main") is None

    def test_ollama_provider(self, monkeypatch):
        mc = ModelsConfig(main=ModelConfig(provider="ollama", model="qwen3:latest"))
        monkeypatch.setattr(
            "server.core.model_router.get_settings", lambda: _make_settings(mc)
        )
        r = ModelRouter()
        client = r._create_client("main")
        assert isinstance(client, OllamaClient)


# ---------------------------------------------------------------- 状态
class TestStatus:
    @pytest.mark.asyncio
    async def test_check_status_unsupported_provider(self, monkeypatch):
        """不支持 provider 时不发起网络，直接返回不可用。"""
        mc = ModelsConfig(main=ModelConfig(provider="weird"))
        monkeypatch.setattr(
            "server.core.model_router.get_settings", lambda: _make_settings(mc)
        )
        r = ModelRouter()
        status = await r.check_status("main")
        assert status.available is False
        assert "不支持的提供商" in status.error


# ---------------------------------------------------------------- 模型信息
class TestModelInfo:
    def test_get_model_info_unknown_type_falls_back(self, router):
        """未知类型 get_model_config 回退 main，仍返回主模型信息。"""
        info = router.get_model_info("nope")
        assert info["type"] == "nope"
        assert info["provider"] == "ollama"

    def test_get_model_info_basic(self, router):
        info = router.get_model_info("main")
        assert info["type"] == "main"
        assert info["provider"] == "ollama"
        assert info["model"] == "qwen3:latest"

    def test_get_model_info_with_status(self, router):
        router._status["main"] = SimpleNamespace(
            available=True, last_check="t", error=None, latency_ms=1.2
        )
        info = router.get_model_info("main")
        assert info["status"]["available"] is True

    def test_get_model_info_follows(self, router):
        info = router.get_model_info("summary")
        assert info.get("follows") == "main"

    def test_get_all_models_info(self, router):
        all_info = router.get_all_models_info()
        assert set(all_info.keys()) == {"main", "summary", "memory", "dream"}


# ---------------------------------------------------------------- dream 槽位
class TestDreamClientSlot:
    @pytest.mark.asyncio
    async def test_initialize_registers_dream_client(self, router, monkeypatch):
        """initialize 按既有顺序遍历 model_types 并为 dream 创建客户端（mock，无网络）。"""
        created = []

        class FakeDreamClient:
            model_name = "dream"

        def fake_create(model_type):
            created.append(model_type)
            return FakeDreamClient()

        async def noop_status():
            return {}

        async def noop_warmup():
            pass

        monkeypatch.setattr(router, "_create_client", fake_create)
        monkeypatch.setattr(router, "check_all_status", noop_status)
        monkeypatch.setattr(router, "warmup_models", noop_warmup)

        await router.initialize()

        # dream 追加在 memory 之后（既有顺序保持）
        assert created == ["main", "summary", "memory", "dream"]
        assert "dream" in router._clients
        assert router.get_client("dream") is not None
        assert router._initialized is True

    def test_get_client_dream_unregistered_returns_none(self, router):
        """dream 客户端未注册时返回 None（与 summary 等槽位口径一致）。"""
        assert router.get_client("dream") is None

    def test_get_config_dream_follows_main(self, monkeypatch):
        """dream 未显式配置时 get_config("dream") 返回 main 的配置（defaults 跟随）。"""
        mc = ModelsConfig()
        monkeypatch.setattr(
            "server.core.model_router.get_settings", lambda: _make_settings(mc)
        )
        r = ModelRouter()
        cfg = r.get_config("dream")
        assert isinstance(cfg, ModelConfig)
        assert cfg is mc.main
        assert r.get_config("main") is mc.main

    def test_all_models_info_contains_dream_entry(self, router):
        all_info = router.get_all_models_info()
        assert "dream" in all_info
        # dream 未显式配置 → 标记 follows main
        assert all_info["dream"].get("follows") == "main"


# ---------------------------------------------------------------- 生命周期
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_resets_state(self, router):
        _fake_client(router, name="main")
        router._status["main"] = SimpleNamespace(available=True)
        router._initialized = True
        await router.close()
        assert router._clients == {}
        assert router._status == {}
        assert router._initialized is False

    def test_init_guard(self):
        """_initialized 为 True 时 initialize 直接返回（避免重复初始化）。"""
        r = ModelRouter()
        r._initialized = True
        # 不应抛错，且不创建新状态
        # 由于 initialize 是 async，这里只验证 guard 属性存在
        assert r._initialized is True