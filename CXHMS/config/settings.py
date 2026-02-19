"""
配置管理模块
支持YAML配置文件、环境变量覆盖和配置验证
"""

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .env import EnvConfig, get_env_config
from .validation import ValidationResult, validate_config

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    VLLM = "vllm"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"
    LOCAL = "local"


class MemoryType(str, Enum):
    PERMANENT = "permanent"
    LONG_TERM = "long_term"
    SHORT_TERM = "short_term"


class AgentStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


class MessageType(str, Enum):
    CHAT = "chat"
    MEMORY_REQUEST = "memory_request"
    MEMORY_RESPONSE = "memory_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    BROADCAST = "broadcast"
    GROUP_MESSAGE = "group_message"
    SYNC = "sync"
    CONTROL = "control"


def deep_merge(base: Dict, override: Dict) -> Dict:
    """深度合并两个字典，override优先"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class ModelConfig:
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    port: int = 8000
    model: str = "llama3.2:3b"
    temperature: float = 0.7
    max_tokens: int = 0
    timeout: int = 60
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelConfig":
        return cls(
            provider=data.get("provider", "ollama"),
            host=data.get("host", "http://localhost:11434"),
            port=data.get("port", 8000),
            model=data.get("model", "llama3.2:3b"),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 0),
            timeout=data.get("timeout", 60),
            api_key=data.get("api_key") or data.get("apiKey"),
        )


@dataclass
class ModelsConfig:
    main: ModelConfig = field(default_factory=ModelConfig)
    summary: ModelConfig = field(default_factory=lambda: ModelConfig(max_tokens=131072))
    memory: ModelConfig = field(default_factory=lambda: ModelConfig(max_tokens=131072))
    defaults: Dict[str, str] = field(default_factory=lambda: {"summary": "main", "memory": "main"})

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelsConfig":
        models_data = data.get("models", {})
        defaults_data = data.get("model_defaults", {"summary": "main", "memory": "main"})

        summary_config = ModelConfig.from_dict(models_data.get("summary", {}))
        if summary_config.max_tokens == 0:
            summary_config.max_tokens = 131072

        memory_config = ModelConfig.from_dict(models_data.get("memory", {}))
        if memory_config.max_tokens == 0:
            memory_config.max_tokens = 131072

        return cls(
            main=ModelConfig.from_dict(models_data.get("main", {})),
            summary=summary_config,
            memory=memory_config,
            defaults=defaults_data,
        )

    def get_model_config(self, model_type: str) -> ModelConfig:
        model_type = model_type.lower()

        if model_type in self.defaults:
            target = self.defaults[model_type]
            if target == "main":
                return self.main
            elif target == "summary":
                return self.summary
            elif target == "memory":
                return self.memory

        if model_type == "main":
            return self.main
        elif model_type == "summary":
            return self.summary
        elif model_type == "memory":
            return self.memory
        else:
            return self.main


@dataclass
class LLMConfig:
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "llama3.2"
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = True
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMConfig":
        return cls(
            provider=data.get("provider", "ollama"),
            host=data.get("host", "http://localhost:11434"),
            model=data.get("model", "llama3.2"),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 4096),
            stream=data.get("stream", True),
            api_key=data.get("api_key"),
        )


@dataclass
class VectorConfig:
    enabled: bool = True
    host: str = "localhost"
    port: int = 6333
    collection_name: str = "cxhms_memories"
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VectorConfig":
        return cls(
            enabled=data.get("enabled", True),
            host=data.get("host", "localhost"),
            port=data.get("port", 6333),
            collection_name=data.get("collection_name", "cxhms_memories"),
            embedding_model=data.get("embedding_model", "nomic-embed-text"),
            embedding_dimension=data.get("embedding_dimension", 768),
            api_key=data.get("api_key"),
        )


@dataclass
class ACPDiscoveryConfig:
    enabled: bool = True
    discovery_port: int = 9999
    broadcast_port: int = 9998
    broadcast_address: str = "255.255.255.255"
    interval: int = 30

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ACPDiscoveryConfig":
        return cls(
            enabled=data.get("enabled", True),
            discovery_port=data.get("discovery_port", 9999),
            broadcast_port=data.get("broadcast_port", 9998),
            broadcast_address=data.get("broadcast_address", "255.255.255.255"),
            interval=data.get("interval", 30),
        )


@dataclass
class ACPConnectionConfig:
    port: int = 10000
    heartbeat_interval: int = 10
    timeout: int = 30

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ACPConnectionConfig":
        return cls(
            port=data.get("port", 10000),
            heartbeat_interval=data.get("heartbeat_interval", 10),
            timeout=data.get("timeout", 30),
        )


@dataclass
class ACPGroupConfig:
    port: int = 10001
    max_members: int = 50

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ACPGroupConfig":
        return cls(port=data.get("port", 10001), max_members=data.get("max_members", 50))


@dataclass
class ACPConfig:
    enabled: bool = True
    agent_id: str = "cxhms-agent-001"
    agent_name: str = "CXHMS Agent"
    discovery: ACPDiscoveryConfig = field(default_factory=ACPDiscoveryConfig)
    connection: ACPConnectionConfig = field(default_factory=ACPConnectionConfig)
    group: ACPGroupConfig = field(default_factory=ACPGroupConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ACPConfig":
        return cls(
            enabled=data.get("enabled", True),
            agent_id=data.get("agent_id", "cxhms-agent-001"),
            agent_name=data.get("agent_name", "CXHMS Agent"),
            discovery=ACPDiscoveryConfig.from_dict(data.get("discovery", {})),
            connection=ACPConnectionConfig.from_dict(data.get("connection", {})),
            group=ACPGroupConfig.from_dict(data.get("group", {})),
        )


@dataclass
class DatabaseConfig:
    path: str = "data/cxhms.db"
    memories_db: str = "data/memories.db"
    sessions_db: str = "data/sessions.db"
    acp_db: str = "data/acp"
    pool_size: int = 10
    max_overflow: int = 20

    @property
    def url(self) -> str:
        return f"sqlite+aiosqlite:///{self.path}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseConfig":
        return cls(
            path=data.get("path", "data/cxhms.db"),
            memories_db=data.get("memories_db", "data/memories.db"),
            sessions_db=data.get("sessions_db", "data/sessions.db"),
            acp_db=data.get("acp_db", "data/acp"),
            pool_size=data.get("pool_size", 10),
            max_overflow=data.get("max_overflow", 20),
        )


@dataclass
class MilvusLiteConfig:
    db_path: str = "data/milvus_lite.db"
    vector_size: int = 768

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MilvusLiteConfig":
        return cls(
            db_path=data.get("db_path", "data/milvus_lite.db"),
            vector_size=data.get("vector_size", 768),
        )


@dataclass
class QdrantConfig:
    host: str = "localhost"
    port: int = 6333
    vector_size: int = 768

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QdrantConfig":
        return cls(
            host=data.get("host", "localhost"),
            port=data.get("port", 6333),
            vector_size=data.get("vector_size", 768),
        )


@dataclass
class WeaviateConfig:
    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    embedded: bool = False
    vector_size: int = 768
    schema_class: str = "CXHMSMemory"
    api_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WeaviateConfig":
        return cls(
            host=data.get("host", "localhost"),
            port=data.get("port", 8080),
            grpc_port=data.get("grpc_port", 50051),
            embedded=data.get("embedded", False),
            vector_size=data.get("vector_size", 768),
            schema_class=data.get("schema_class", "CXHMSMemory"),
            api_key=data.get("api_key"),
        )


@dataclass
class MemoryConfig:
    decay_enabled: bool = True
    batch_interval: int = 3600
    permanent_threshold: float = 0.95
    max_short_term_age_days: int = 7
    max_long_term_age_days: int = 365
    vector_enabled: bool = True
    vector_backend: str = "milvus_lite"
    milvus_lite: MilvusLiteConfig = field(default_factory=MilvusLiteConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    weaviate: WeaviateConfig = field(default_factory=WeaviateConfig)
    archive_enabled: bool = True
    dedup_threshold: float = 0.85
    archive_compression_enabled: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryConfig":
        return cls(
            decay_enabled=data.get("decay_enabled", True),
            batch_interval=data.get("batch_interval", 3600),
            permanent_threshold=data.get("permanent_threshold", 0.95),
            max_short_term_age_days=data.get("max_short_term_age_days", 7),
            max_long_term_age_days=data.get("max_long_term_age_days", 365),
            vector_enabled=data.get("vector_enabled", True),
            vector_backend=data.get("vector_backend", "milvus_lite"),
            milvus_lite=MilvusLiteConfig.from_dict(data.get("milvus_lite", {})),
            qdrant=QdrantConfig.from_dict(data.get("qdrant", {})),
            weaviate=WeaviateConfig.from_dict(data.get("weaviate", {})),
            archive_enabled=data.get("archive_enabled", True),
            dedup_threshold=data.get("dedup_threshold", 0.85),
            archive_compression_enabled=data.get("archive_compression_enabled", True),
        )


@dataclass
class ContextConfig:
    max_messages: int = 100
    summary_threshold: int = 20
    window_size: int = 10
    enable_summary: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextConfig":
        return cls(
            max_messages=data.get("max_messages", 100),
            summary_threshold=data.get("summary_threshold", 20),
            window_size=data.get("window_size", 10),
            enable_summary=data.get("enable_summary", True),
        )


@dataclass
class RateLimitConfig:
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RateLimitConfig":
        return cls(enabled=data.get("enabled", True))


@dataclass
class CORSConfig:
    enabled: bool = True
    origins: List[str] = field(default_factory=lambda: ["*"])
    allow_credentials: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CORSConfig":
        return cls(
            enabled=data.get("enabled", True),
            origins=data.get("origins", ["*"]),
            allow_credentials=data.get("allow_credentials", True),
        )


@dataclass
class SystemConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    workers: int = 1

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemConfig":
        return cls(
            host=data.get("host", "0.0.0.0"),
            port=data.get("port", 8000),
            debug=data.get("debug", False),
            log_level=data.get("log_level", "INFO"),
            workers=data.get("workers", 1),
        )


@dataclass
class CXHMSConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    vector: VectorConfig = field(default_factory=VectorConfig)
    acp: ACPConfig = field(default_factory=ACPConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    cors: CORSConfig = field(default_factory=CORSConfig)
    system: SystemConfig = field(default_factory=SystemConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CXHMSConfig":
        server_data = data.get("server", data.get("system", {}))
        return cls(
            llm=LLMConfig.from_dict(data.get("llm", {})),
            models=ModelsConfig.from_dict(data),
            vector=VectorConfig.from_dict(data.get("vector", {})),
            acp=ACPConfig.from_dict(data.get("acp", {})),
            database=DatabaseConfig.from_dict(data.get("database", {})),
            memory=MemoryConfig.from_dict(data.get("memory", {})),
            context=ContextConfig.from_dict(data.get("context", {})),
            rate_limit=RateLimitConfig.from_dict(data.get("rate_limit", {})),
            cors=CORSConfig.from_dict(data.get("cors", {})),
            system=SystemConfig.from_dict(server_data),
        )


class Settings:
    _instance: Optional["Settings"] = None
    _config: Optional[CXHMSConfig] = None
    _config_path: Optional[str] = None
    _validation_result: Optional[ValidationResult] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._config = self.load_config()

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._config = None
        cls._config_path = None
        cls._validation_result = None

    @property
    def config(self) -> CXHMSConfig:
        return self._config

    @property
    def validation_result(self) -> Optional[ValidationResult]:
        return self._validation_result

    def load_config(self, config_path: Optional[str] = None) -> CXHMSConfig:
        if config_path is None:
            config_path = os.getenv("CXHMS_CONFIG_PATH", "config/default.yaml")

        self._config_path = config_path
        config_file = Path(config_path)

        file_config: Dict[str, Any] = {}
        if config_file.exists():
            with open(config_file, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}

        env_config = get_env_config()

        merged_config = deep_merge(file_config, env_config)

        self._validation_result = validate_config(merged_config)
        if not self._validation_result.is_valid:
            for error in self._validation_result.errors:
                logger.error(f"配置验证失败: {error}")

        for field, message in self._validation_result.warnings:
            logger.warning(f"配置警告 [{field}]: {message}")

        return CXHMSConfig.from_dict(merged_config)

    def reload_config(self, config_path: Optional[str] = None):
        self._config = self.load_config(config_path)
        logger.info("配置已重新加载")

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            elif hasattr(value, k):
                value = getattr(value, k)
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        keys = key.split(".")
        target = self._config
        for k in keys[:-1]:
            if isinstance(target, dict):
                target = target.get(k)
            elif hasattr(target, k):
                target = getattr(target, k)

        final_key = keys[-1]
        if isinstance(target, dict):
            target[final_key] = value
        elif hasattr(target, final_key):
            setattr(target, final_key, value)

    def save_config(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = self._config_path or "config/default.yaml"
        config_dict = self._config_to_dict(self._config)

        masked_config = EnvConfig.mask_secrets(config_dict)

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(masked_config, f, allow_unicode=True, indent=2)

    def _config_to_dict(self, config: Any) -> Dict[str, Any]:
        if isinstance(config, dict):
            return {k: self._config_to_dict(v) for k, v in config.items()}
        elif hasattr(config, "__dict__"):
            return {
                k: self._config_to_dict(v)
                for k, v in config.__dict__.items()
                if not k.startswith("_")
            }
        elif isinstance(config, (list, tuple)):
            return [self._config_to_dict(item) for item in config]
        else:
            return config

    def get_debug_info(self) -> Dict[str, Any]:
        return {
            "config_path": self._config_path,
            "validation": {
                "is_valid": self._validation_result.is_valid if self._validation_result else None,
                "errors": (
                    [str(e) for e in self._validation_result.errors]
                    if self._validation_result
                    else []
                ),
                "warnings": self._validation_result.warnings if self._validation_result else [],
            },
            "env_overrides": list(EnvConfig.ENV_MAPPINGS.keys()),
        }


settings = Settings()
