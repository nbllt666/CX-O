"""
图数据库配置管理
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class WeaviateConfig:
    """Weaviate 配置"""
    url: str = "http://localhost:8080"
    api_key: Optional[str] = None
    vector_dim: int = 384
    batch_size: int = 100
    ef_construction: int = 128
    max_connections: int = 16


@dataclass
class EmbeddingConfig:
    """向量化配置"""
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 32
    device: str = "cpu"
    cache_folder: Optional[str] = None


@dataclass
class GraphConfig:
    """图数据库配置"""
    database_path: str = "data/graph.db"
    auto_create_schema: bool = True
    pool_size: int = 10
    timeout: int = 30
    weaviate: WeaviateConfig = field(default_factory=WeaviateConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)


_config: Optional[GraphConfig] = None


def get_graph_config() -> GraphConfig:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = _load_config_from_env()
    return _config


def _load_config_from_env() -> GraphConfig:
    """从环境变量加载配置"""
    return GraphConfig(
        database_path=os.getenv("GRAPH_DATABASE_PATH", "data/graph.db"),
        auto_create_schema=os.getenv("GRAPH_AUTO_CREATE", "true").lower() == "true",
        pool_size=int(os.getenv("GRAPH_POOL_SIZE", "10")),
        timeout=int(os.getenv("GRAPH_TIMEOUT", "30")),
        weaviate=WeaviateConfig(
            url=os.getenv("WEAVIATE_URL", "http://localhost:8080"),
            api_key=os.getenv("WEAVIATE_API_KEY"),
            vector_dim=int(os.getenv("WEAVIATE_VECTOR_DIM", "384")),
            batch_size=int(os.getenv("WEAVIATE_BATCH_SIZE", "100")),
            ef_construction=int(os.getenv("WEAVIATE_EF_CONSTRUCTION", "128")),
            max_connections=int(os.getenv("WEAVIATE_MAX_CONNECTIONS", "16")),
        ),
        embedding=EmbeddingConfig(
            model=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
            batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
            device=os.getenv("EMBEDDING_DEVICE", "cpu"),
            cache_folder=os.getenv("EMBEDDING_CACHE_FOLDER"),
        ),
    )


def set_graph_config(config: GraphConfig) -> None:
    """设置全局配置实例"""
    global _config
    _config = config
