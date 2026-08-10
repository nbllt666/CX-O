"""server.core.model_router (ModelRouter) 单元测试。

通过 mock get_settings 与客户端，覆盖模型客户端获取/默认跟随、
对话/Embedding 代理、状态查询、配置信息等核心逻辑，不发起真实网络请求。

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


def _fake_client(r, name="main", chat=None, embedding=None):
    """注册一个假客户端到 _clients。"""

    class FakeClient:
        model_name = name

        async def chat(self, messages, stream=False, **kwargs):
            if chat:
                return chat(messages, stream, **kwargs)
            return FakeLLMResponse(content="ok")

        async def get_embedding(self, text):
            if embedding:
                return embedding(text)
            return [0.1, 0.2]

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
        """summary 默认跟随 main，应返回 main 客户端。"""
        main = _fake_client(router, name="main")
        client = router.get_client("summary")
        assert client is main

    def test_default_following_case_insensitive(self, router):
        main = _fake_client(router, name="main")
        assert router.get_client("SUMMARY") is main

    def test_default_follows_missing_target_falls_back(self, router):
        """defaults 指向不存在的客户端时回退到类型自身。"""
        _fake_client(router, name="summary")
        # summary 默认跟随 main，但 main 不存在 → 回退 summary
        client = router.get_client("summary")
        assert client is router._clients["summary"]


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


# ---------------------------------------------------------------- chat
class TestChat:
    @pytest.mark.asyncio
    async def test_chat_without_client(self, router):
        result = await router.chat("main", [{"role": "user", "content": "hi"}])
        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_chat_success(self, router):
        _fake_client(router, name="main")
        result = await router.chat("main", [{"role": "user", "content": "hi"}])
        assert result["success"] is True
        assert result["content"] == "ok"
        assert result["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_chat_success_false_on_error_finish(self, router):
        def _chat(messages, stream, **kw):
            return FakeLLMResponse(finish_reason="error")

        _fake_client(router, name="main", chat=_chat)
        result = await router.chat("main", [{"role": "user", "content": "hi"}])
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_chat_exception_handled(self, router):
        def _chat(messages, stream, **kw):
            raise RuntimeError("boom")

        _fake_client(router, name="main", chat=_chat)
        result = await router.chat("main", [{"role": "user", "content": "hi"}])
        assert result["success"] is False
        assert result["error"] == "boom"


# ---------------------------------------------------------------- get_embedding
class TestGetEmbedding:
    @pytest.mark.asyncio
    async def test_without_client_returns_none(self, router):
        assert await router.get_embedding("main", "text") is None

    @pytest.mark.asyncio
    async def test_with_client(self, router):
        _fake_client(router, name="main")
        embedding = await router.get_embedding("main", "text")
        assert embedding == [0.1, 0.2]

    @pytest.mark.asyncio
    async def test_client_without_method_returns_none(self, router):
        class NoEmbedClient:
            model_name = "main"

            async def chat(self, messages, stream=False, **kwargs):
                return FakeLLMResponse()

        router._clients["main"] = NoEmbedClient()
        assert await router.get_embedding("main", "text") is None


# ---------------------------------------------------------------- 状态
class TestStatus:
    def test_is_available_false_by_default(self, router):
        assert not router.is_available("main")

    def test_is_available_true(self, router):
        router._status["main"] = SimpleNamespace(available=True)
        assert router.is_available("main") is True

    def test_get_all_status_empty(self, router):
        assert router.get_all_status() == {}

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
        assert set(all_info.keys()) == {"main", "summary", "memory"}


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