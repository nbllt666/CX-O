"""
文本向量化
"""

import hashlib
import logging
from typing import List, Optional
import numpy as np

from server.core.graph.config import EmbeddingConfig, get_graph_config

logger = logging.getLogger(__name__)

_vectorizer: Optional["TextVectorizer"] = None


class TextVectorizer:
    """文本向量化器"""

    def __init__(self, config: EmbeddingConfig = None):
        """初始化文本向量化器（缺省使用全局配置）。"""
        self.config = config or get_graph_config().embedding
        self._model = None
        self._device = self.config.device

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(
                    self.config.model,
                    device=self._device,
                    cache_folder=self.config.cache_folder,
                )
                logger.info(f"加载文本向量化模型: {self.config.model} (device={self._device})")
            except ImportError:
                logger.warning("sentence-transformers 未安装，使用简化的向量化")
                self._model = None

    def encode(self, text: str) -> np.ndarray:
        self._load_model()

        if self._model is None:
            return self._simple_encode(text)

        embeddings = self._model.encode(
            text,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embeddings

    def encode_batch(self, texts: List[str], show_progress: bool = False) -> np.ndarray:
        self._load_model()

        if self._model is None:
            return np.array([self._simple_encode(t) for t in texts])

        embeddings = self._model.encode(
            texts,
            batch_size=self.config.batch_size,
            convert_to_numpy=True,
            show_progress_bar=show_progress,
        )
        return embeddings

    def _simple_encode(self, text: str) -> np.ndarray:
        words = text.split()
        vector = np.zeros(self.config.vector_dim, dtype=np.float32)
        for i, word in enumerate(words[:self.config.vector_dim]):
            vector[i] = int(hashlib.sha256(word.encode()).hexdigest(), 16) % 1000 / 1000.0
        return vector

    def get_dimension(self) -> int:
        return self.config.vector_dim

    def close(self):
        """释放模型资源。"""
        if self._model:
            del self._model
            self._model = None


def get_vectorizer() -> TextVectorizer:
    """获取全局单例向量化器实例。"""
    global _vectorizer
    if _vectorizer is None:
        _vectorizer = TextVectorizer()
    return _vectorizer
