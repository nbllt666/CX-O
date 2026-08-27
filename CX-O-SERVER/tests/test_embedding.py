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
    # H14: 整体请求失败不得返回零向量占位——改为全部过滤返回 []，杜绝零向量入库
    _mock_client(monkeypatch, status=500)
    model = VLLMEmbedding(dimension=4)
    result = await model.get_embeddings(["a", "b"])
    assert result == []
    assert all(emb != [0.0] * 4 for emb in result)


@pytest.mark.asyncio
async def test_ollama_get_embeddings_failure_filtered(monkeypatch):
    """H14: Ollama 批量嵌入失败条目过滤不入库（不再零向量占位），成功条目保留。"""
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"embedding": [0.5]}
    bad = MagicMock()
    bad.status_code = 500

    responses = iter([ok, bad])
    mock_client = AsyncMock()
    mock_client.post.side_effect = lambda *a, **k: next(responses)
    monkeypatch.setattr(
        "server.core.memory.embedding.get_shared_http_client", lambda: mock_client
    )

    model = OllamaEmbedding()
    result = await model.get_embeddings(["good", "bad"])
    assert result == [[0.5]]


@pytest.mark.asyncio
async def test_vllm_get_embeddings_partial_missing_filtered(monkeypatch):
    """H14: vLLM 返回条目缺失/为空时仅保留有效项并过滤占位。"""
    _mock_client(
        monkeypatch,
        payload={
            "data": [
                {"index": 0, "embedding": [1.0]},
                {"index": 1, "embedding": []},  # 空嵌入 → 过滤
            ]
        },
    )
    model = VLLMEmbedding(dimension=3)
    result = await model.get_embeddings(["a", "b"])
    assert result == [[1.0]]
    assert not any(all(v == 0 for v in emb) for emb in result)


class TestEmbeddingFactoryCacheKey:
    def test_same_endpoint_reuses_instance(self):
        m1 = EmbeddingFactory.create("ollama", model="m", host="http://h1:11434")
        m2 = EmbeddingFactory.create("ollama", model="m", host="http://h1:11434")
        assert m1 is m2

    def test_different_host_not_shared(self):
        """H14: 缓存键并入 host——不同服务地址的同名模型不互串实例。"""
        EmbeddingFactory.clear_cache()
        try:
            m1 = EmbeddingFactory.create("ollama", model="cm", host="http://h1:11434")
            m2 = EmbeddingFactory.create("ollama", model="cm", host="http://h2:11434")
            assert m1 is not m2
            assert m1.host != m2.host
        finally:
            EmbeddingFactory.clear_cache()

    def test_different_api_base_not_shared(self):
        EmbeddingFactory.clear_cache()
        try:
            m1 = EmbeddingFactory.create("vllm", model="vm", api_base="http://a1:8000")
            m2 = EmbeddingFactory.create("vllm", model="vm", api_base="http://a2:8000")
            assert m1 is not m2
        finally:
            EmbeddingFactory.clear_cache()

    def test_api_key_never_in_cache_identity(self):
        """api_key 不参与缓存键：不同 key 的同端点模型复用同一实例，且键中无 key。"""
        EmbeddingFactory.clear_cache()
        try:
            m1 = EmbeddingFactory.create("vllm", model="km", api_base="http://k:8000", api_key="secret-A")
            m2 = EmbeddingFactory.create("vllm", model="km", api_base="http://k:8000", api_key="secret-B")
            assert m1 is m2  # 复用而非新实例 → key 未参与身份
        finally:
            EmbeddingFactory.clear_cache()


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