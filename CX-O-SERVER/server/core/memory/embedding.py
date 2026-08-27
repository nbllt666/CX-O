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
        """批量计算文本嵌入。

        H14: 失败条目不再以零向量占位（零向量入库会污染相似度排序），
        而是直接过滤掉不返回；由此导致的召回量减少会记录 warning 日志。
        返回列表长度可能小于 len(texts)，调用方不得按位置对齐。
        """
        embeddings = []
        failed_texts = []
        for text in texts:
            emb = await self.get_embedding(text)
            if emb:
                embeddings.append(emb)
            else:
                failed_texts.append(text)
        if failed_texts:
            # 占位不入库 → 召回量减少，必须留痕提示
            logger.warning(
                f"{len(failed_texts)}/{len(texts)} 条文本嵌入失败，已过滤不入库"
                f"（召回量将减少），示例: {failed_texts[0][:50]!r}..."
            )
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
        """批量请求全部文本嵌入，按返回的 index 排序。

        H14: 整体请求失败或返回条目嵌入缺失时，不再用零向量占位——
        直接过滤并 warning 提示召回量减少，避免零向量污染向量库与排序。
        """
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
                # data is a list of {"index": i, "embedding": [...]}
                filtered = [
                    d.get("embedding") for d in sorted(data, key=lambda x: x.get("index", 0))
                    if d.get("embedding")
                ]
                missing = len(texts) - len(filtered)
                if missing > 0:
                    logger.warning(
                        f"vLLM 批量嵌入 {missing}/{len(texts)} 条缺失/为空，已过滤不入库"
                        f"（召回量将减少）"
                    )
                return filtered
            else:
                logger.error(f"vLLM 批量嵌入失败: {response.status_code}")
                logger.warning(
                    f"vLLM 批量嵌入整体失败，{len(texts)} 条全部过滤不入库（召回量将减少）"
                )
                return []
        except Exception as e:
            logger.error(f"获取 vLLM 批量嵌入失败: {e}")
            logger.warning(
                f"vLLM 批量嵌入异常，{len(texts)} 条全部过滤不入库（召回量将减少）"
            )
            return []

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
        """按 provider 创建嵌入模型实例，命中缓存直接返回。

        H14: 缓存键并入 host/api_base——同一模型名但不同服务地址的实例
        不得互串缓存；api_key 不参与缓存键也不进日志（避免凭据泄露）。
        """
        endpoint = kwargs.get("host") or kwargs.get("api_base") or ""
        key = f"{provider}:{kwargs.get('model', 'default')}@{endpoint}"

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
