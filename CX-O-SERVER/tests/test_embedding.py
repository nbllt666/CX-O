"""server.core.memory.embedding 单元测试。

通过 mock httpx.AsyncClient 隔离网络，覆盖 OllamaEmbedding / VLLMEmbedding 的
embedding 获取/批量/失败回退，以及 EmbeddingFactory 分发/缓存/不支持 provider。
运行：python -m pytest tests/test_embedding.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from server.core.memory.embedding import (
    EmbeddingFactory,
    OllamaEmbedding,
    VLLMEmbedding,
)


def _mock_client(monkeypatch, status=200, payload=None):
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_response.json.return_value = payload or {"embedding": [0.1, 0.2, 0.3]}
    mock_response.text = "error body"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    monkeypatch.setattr("server.core.memory.embedding.get_shared_http_client", lambda: mock_client)
    return mock_client


@pytest.mark.asyncio
async def test_ollama_get_embedding(monkeypatch):
    mock = _mock_client(monkeypatch, payload={"embedding": [1.0, 2.0, 3.0]})
    model = OllamaEmbedding(host="http://localhost:11434", model="nomic-embed-text")
    result = await model.get_embedding("hello")
    assert result == [1.0, 2.0, 3.0]
    # 校验请求 URL 与方法
    mock.post.assert_called_once()
    args, kwargs = mock.post.call_args
    assert args[0] == "http://localhost:11434/api/embeddings"
    assert kwargs["json"]["model"] == "nomic-embed-text"


@pytest.mark.asyncio
async def test_ollama_get_embedding_error(monkeypatch):
    _mock_client(monkeypatch, status=500)
    model = OllamaEmbedding()
    assert await model.get_embedding("x") == []


@pytest.mark.asyncio
async def test_ollama_get_embeddings(monkeypatch):
    _mock_client(monkeypatch, payload={"embedding": [0.5]})
    model = OllamaEmbedding()
    result = await model.get_embeddings(["a", "b"])
    assert result == [[0.5], [0.5]]


def test_ollama_dimension_and_name():
    model = OllamaEmbedding(model="nomic-embed-text")
    assert model.dimension == 768
    assert model.name == "ollama/nomic-embed-text"


@pytest.mark.asyncio
async def test_vllm_get_embedding(monkeypatch):
    mock = _mock_client(monkeypatch, payload={"data": [{"index": 0, "embedding": [0.9]}]})
    model = VLLMEmbedding(model="bge-m3", api_base="http://localhost:8000")
    result = await model.get_embedding("hi")
    assert result == [0.9]
    args, kwargs = mock.post.call_args
    assert args[0] == "http://localhost:8000/v1/embeddings"


@pytest.mark.asyncio
async def test_vllm_get_embedding_empty_data(monkeypatch):
    _mock_client(monkeypatch, payload={"data": []})
    model = VLLMEmbedding()
    assert await model.get_embedding("hi") == []


@pytest.mark.asyncio
async def test_vllm_get_embeddings_sorted_by_index(monkeypatch):
    _mock_client(
        monkeypatch,
        payload={
            "data": [
                {"index": 1, "embedding": [2.0]},
                {"index": 0, "embedding": [1.0]},
            ]
        },
    )
    model = VLLMEmbedding()
    result = await model.get_embeddings(["a", "b"])
    assert result == [[1.0], [2.0]]


@pytest.mark.asyncio
async def test_vllm_get_embeddings_error_zero(monkeypatch):
    _mock_client(monkeypatch, status=500)
    model = VLLMEmbedding(dimension=4)
    result = await model.get_embeddings(["a", "b"])
    assert result == [[0.0] * 4, [0.0] * 4]


def test_vllm_props():
    model = VLLMEmbedding(model="bge-m3", dimension=1024)
    assert model.dimension == 1024
    assert model.name == "vllm/bge-m3"


class TestEmbeddingFactory:
    def test_create_ollama(self):
        model = EmbeddingFactory.create("ollama", model="nomic-embed-text")
        assert isinstance(model, OllamaEmbedding)

    def test_factory_cache_reuse(self):
        m1 = EmbeddingFactory.create("ollama", model="m")
        m2 = EmbeddingFactory.create("ollama", model="m")
        assert m1 is m2

    def test_clear_cache(self):
        m1 = EmbeddingFactory.create("vllm", model="m")
        EmbeddingFactory.clear_cache()
        m2 = EmbeddingFactory.create("vllm", model="m")
        assert m1 is not m2

    def test_unsupported_provider(self):
        with pytest.raises(ValueError):
            EmbeddingFactory.create("unknown")

    def test_list_providers(self):
        assert set(EmbeddingFactory.list_available_providers()) == {
            "ollama",
            "sentence-transformers",
            "vllm",
        }