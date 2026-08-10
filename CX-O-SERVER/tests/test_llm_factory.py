"""server.core.llm.client.LLMFactory 单元测试。

覆盖 provider 工厂分发、客户端缓存复用、不支持 provider 报错、缓存清理。

运行：python -m pytest tests/test_llm_factory.py -v
"""
import pytest

from server.core.llm.client import LLMFactory


@pytest.fixture(autouse=True)
def _clear_cache():
    LLMFactory.clear_cache()
    yield
    LLMFactory.clear_cache()


class TestLLMFactory:
    def test_create_ollama(self):
        client = LLMFactory.create_client("ollama", model="qwen3:latest")
        from server.core.llm.client import OllamaClient

        assert isinstance(client, OllamaClient)
        assert client.model == "qwen3:latest"

    def test_create_vllm(self):
        from server.core.llm.client import VLLMClient

        assert isinstance(LLMFactory.create_client("vllm"), VLLMClient)

    def test_create_trtllm(self):
        from server.core.llm.client import TRTLLMClient

        assert isinstance(LLMFactory.create_client("trtllm"), TRTLLMClient)

    def test_unsupported_provider(self):
        with pytest.raises(ValueError, match="不支持的LLM提供商"):
            LLMFactory.create_client("weird")

    def test_cache_reuses_same_instance(self):
        a = LLMFactory.create_client("ollama", model="m1")
        b = LLMFactory.create_client("ollama", model="m1")
        assert a is b

    def test_different_model_creates_new(self):
        a = LLMFactory.create_client("ollama", model="m1")
        b = LLMFactory.create_client("ollama", model="m2")
        assert a is not b

    def test_get_client_delegates(self):
        assert LLMFactory.get_client("ollama") is LLMFactory.get_client("ollama")

    def test_clear_cache_invalidates(self):
        a = LLMFactory.create_client("ollama", model="m1")
        LLMFactory.clear_cache()
        b = LLMFactory.create_client("ollama", model="m1")
        assert a is not b