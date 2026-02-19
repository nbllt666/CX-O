import os
import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

os.environ["HF_HUB_DOWNLOAD_PROGRESS"] = "1"

logger = get_contextual_logger(__name__)


class EmbeddingModel(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> List[float]:
        pass

    @abstractmethod
    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


class OllamaEmbedding(EmbeddingModel):
    def __init__(self, host: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        self.host = host.rstrip("/")
        self.model = model
        self._client = None

    def _get_client(self):
        import httpx

        return httpx.AsyncClient(timeout=60.0)

    async def get_embedding(self, text: str) -> List[float]:
        try:
            async with self._get_client() as client:
                response = await client.post(
                    f"{self.host}/api/embeddings", json={"model": self.model, "prompt": text}
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
        return 768

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"


class SentenceTransformersEmbedding(EmbeddingModel):
    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        try:
            import sys

            from sentence_transformers import SentenceTransformer

            print(f"\n正在加载 SentenceTransformers 模型: {model_name}", file=sys.stderr)
            print("这可能需要几分钟时间下载模型...", file=sys.stderr)
            sys.stderr.flush()

            self.model = SentenceTransformer(model_name)
            self._model_name = model_name

            print(f"✓ SentenceTransformers 模型加载成功: {model_name}", file=sys.stderr)
            logger.info(f"SentenceTransformers模型加载成功: {model_name}")
        except ImportError:
            logger.error("sentence-transformers未安装")
            raise ImportError("请安装: pip install sentence-transformers")

    async def get_embedding(self, text: str) -> List[float]:
        import asyncio

        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(None, lambda: self.model.encode(text).tolist())
        return embedding

    async def get_embeddings(self, texts: List[str]) -> List[List[float]]:
        import asyncio

        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(None, lambda: self.model.encode(texts).tolist())
        return embeddings

    @property
    def dimension(self) -> int:
        return self.model.get_sentence_embedding_dimension()

    @property
    def name(self) -> str:
        return f"sentence-transformers/{self._model_name}"


class EmbeddingFactory:
    _models: dict = {}
    _lock = threading.Lock()

    @classmethod
    def create(cls, provider: str = "ollama", **kwargs) -> EmbeddingModel:
        key = f"{provider}:{kwargs.get('model', 'default')}"

        with cls._lock:
            if key in cls._models:
                return cls._models[key]

            if provider == "ollama":
                model = OllamaEmbedding(**kwargs)
            elif provider == "sentence-transformers":
                model = SentenceTransformersEmbedding(**kwargs)
            else:
                raise ValueError(f"不支持的嵌入模型: {provider}")

            cls._models[key] = model
            return model

    @classmethod
    def get_model(cls, provider: str = "ollama", **kwargs) -> EmbeddingModel:
        return cls.create(provider, **kwargs)

    @classmethod
    def clear_cache(cls):
        with cls._lock:
            cls._models.clear()

    @classmethod
    def list_available_providers(cls) -> List[str]:
        return ["ollama", "sentence-transformers"]
