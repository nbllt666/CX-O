"""文本嵌入抽象与实现。

定义统一的 EmbeddingProvider 抽象基类及基于 HTTP/本地模型的实现，
供记忆向量化（向量存储 / 混合检索）使用，通过 get_shared_http_client 复用
连接池以避免逐请求建连。
"""
import os
import threading
from abc import ABC, abstractmethod
from typing import List

from server.core.logging_config import get_contextual_logger
from server.core.utils import get_shared_http_client

os.environ["HF_HUB_DOWNLOAD_PROGRESS"] = "1"

logger = get_contextual_logger(__name__)


class EmbeddingModel(ABC):
    """嵌入模型抽象基类：定义单条/批量嵌入、维度与名称的统一接口。"""

    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        """计算单条文本的嵌入向量。"""
        pass

    @abstractmethod
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """批量计算多条文本的嵌入向量。"""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """返回嵌入向量维度。"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """返回模型名称标识。"""
        pass


class OllamaEmbedding(EmbeddingModel):
    """基于 Ollama 文本嵌入接口的嵌入实现。"""

    def __init__(self, host: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        """初始化 Ollama 嵌入客户端，保存服务地址与模型名。"""
        self.host = host.rstrip("/")
        self.model = model

    async def get_embedding(self, text: str) -> List[float]:
        """计算单条文本嵌入，失败时返回空列表。"""
        try:
            # 复用 shared HTTP 连接池，避免每次调用都构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.post(
                f"{self.host}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=60.0,
            )
            if response.status_code == 200:
                result = response.json()
                return result.get("embedding", [])
            else:
                logger.error(f"嵌入失败: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"获取嵌入失败: {e}")
            return []

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """批量计算文本嵌入，失败的条目用零向量占位。"""
        embeddings = []
        for text in texts:
            emb = await self.get_embedding(text)
            if emb:
                embeddings.append(emb)
            else:
                logger.warning(f"文本嵌入失败: {text[:50]}...")
                embeddings.append([0.0] * self.dimension)
        return embeddings

    @property
    def dimension(self) -> int:
        """返回嵌入向量维度（固定 768）。"""
        return 768

    @property
    def name(self) -> str:
        """返回模型名称标识（如 ollama/<model>）。"""
        return f"ollama/{self.model}"


class SentenceTransformersEmbedding(EmbeddingModel):
    """基于本地 sentence-transformers 模型的嵌入实现。"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        """初始化并加载本地 sentence-transformers 模型。"""
        try:
            pass

            from sentence_transformers import SentenceTransformer

            logger.info(f"正在加载 SentenceTransformers 模型: {model_name}")

            self.model = SentenceTransformer(model_name)
            self._model_name = model_name

            logger.info(f"SentenceTransformers 模型加载成功: {model_name}")
        except ImportError:
            logger.error("sentence-transformers未安装")
            raise ImportError("请安装: pip install sentence-transformers")

    async def get_embedding(self, text: str) -> List[float]:
        """在线程池中计算单条文本嵌入。"""
        import asyncio

        loop = asyncio.get_running_loop()
        embedding = await loop.run_in_executor(None, lambda: self.model.encode(text).tolist())
        return embedding

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """在线程池中批量计算文本嵌入。"""
        import asyncio

        loop = asyncio.get_running_loop()
        embeddings = await loop.run_in_executor(None, lambda: self.model.encode(texts).tolist())
        return embeddings

    @property
    def dimension(self) -> int:
        """返回模型嵌入维度。"""
        return self.model.get_sentence_embedding_dimension()

    @property
    def name(self) -> str:
        """返回模型名称标识。"""
        return f"sentence-transformers/{self._model_name}"


class VLLMEmbedding(EmbeddingModel):
    """基于 vLLM OpenAI 兼容 /v1/embeddings 接口的嵌入实现。"""

    def __init__(self, model: str = "bge-m3", api_base: str = "http://localhost:8000", api_key: str = "", dimension: int = 1024):
        self.model = model
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self._dimension = dimension

    def _headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def get_embedding(self, text: str) -> List[float]:
        """计算单条文本嵌入，失败时返回空列表。"""
        try:
            # 复用 shared HTTP 连接池，避免每次调用都构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.post(
                f"{self.api_base}/v1/embeddings",
                json={"model": self.model, "input": text},
                headers=self._headers(),
                timeout=60.0,
            )
            if response.status_code == 200:
                result = response.json()
                data = result.get("data", [])
                if data and "embedding" in data[0]:
                    return data[0]["embedding"]
                return []
            else:
                logger.error(f"vLLM 嵌入失败: {response.status_code} {response.text}")
                return []
        except Exception as e:
            logger.error(f"获取 vLLM 嵌入失败: {e}")
            return []

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        """批量请求全部文本嵌入，按返回的 index 排序，失败时用零向量占位。"""
        # batch request: send all texts in one request, map by index
        try:
            # 复用 shared HTTP 连接池，避免每次调用都构造 httpx.AsyncClient
            client = get_shared_http_client()
            response = await client.post(
                f"{self.api_base}/v1/embeddings",
                json={"model": self.model, "input": texts},
                headers=self._headers(),
                timeout=60.0,
            )
            if response.status_code == 200:
                result = response.json()
                data = result.get("data", [])
                # data is a list of {"index": i, "embedding": [...]}; sort by index
                data_sorted = sorted(data, key=lambda x: x.get("index", 0))
                return [d.get("embedding", []) for d in data_sorted]
            else:
                logger.error(f"vLLM 批量嵌入失败: {response.status_code}")
                return [[0.0] * self._dimension for _ in texts]
        except Exception as e:
            logger.error(f"获取 vLLM 批量嵌入失败: {e}")
            return [[0.0] * self._dimension for _ in texts]

    @property
    def dimension(self) -> int:
        """返回嵌入向量维度。"""
        return self._dimension

    @property
    def name(self) -> str:
        """返回模型名称标识（如 vllm/<model>）。"""
        return f"vllm/{self.model}"


class EmbeddingFactory:
    """嵌入模型工厂：按 provider 创建并缓存单例模型实例。"""

    _models: dict = {}
    _lock = threading.Lock()

    @classmethod
    def create(cls, provider: str = "ollama", **kwargs) -> EmbeddingModel:
        """按 provider 创建嵌入模型实例，命中缓存直接返回。"""
        key = f"{provider}:{kwargs.get('model', 'default')}"

        with cls._lock:
            if key in cls._models:
                return cls._models[key]

            if provider == "ollama":
                model = OllamaEmbedding(**kwargs)
            elif provider == "sentence-transformers":
                model = SentenceTransformersEmbedding(**kwargs)
            elif provider == "vllm":
                model = VLLMEmbedding(**kwargs)
            else:
                raise ValueError(f"不支持的嵌入模型: {provider}")

            cls._models[key] = model
            return model

    @classmethod
    def clear_cache(cls):
        """清空已缓存的模型实例。"""
        with cls._lock:
            cls._models.clear()

    @classmethod
    def list_available_providers(cls) -> List[str]:
        """返回当前支持的嵌入 provider 列表。"""
        return ["ollama", "sentence-transformers", "vllm"]
