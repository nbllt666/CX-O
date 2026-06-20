"""
CX-O-SERVER 统一配置模块
合并 gateway/config.py、config/settings.py 和原 server/config.py 为单一 Pydantic 配置模型
从 config.json 读取，支持 CXO_ 前缀环境变量覆盖
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from server.core.utils import deep_merge


ENV_PREFIX = "CXO_"


def get_env_config() -> Dict[str, Any]:
    env_config: Dict[str, Any] = {}

    _env_mappings: Dict[str, List[str]] = {
        "CXO_SYSTEM_HOST": ["system", "host"],
        "CXO_SYSTEM_PORT": ["system", "port"],
        "CXO_SYSTEM_DEBUG": ["system", "debug"],
        "CXO_SYSTEM_LOG_LEVEL": ["system", "log_level"],
        "CXO_SYSTEM_WORKERS": ["system", "workers"],
        "CXO_GATEWAY_HOST": ["gateway", "host"],
        "CXO_GATEWAY_PORT": ["gateway", "port"],
        "CXO_GATEWAY_CONFIG": [],
        "CXO_ASR_MODE": ["asr", "mode"],
        "CXO_ASR_MODEL_DIR": ["asr", "model_dir"],
        "CXO_ASR_DEVICE": ["asr", "device"],
        "CXO_ASR_REMOTE_URL": ["asr", "remote_url"],
        "CXO_TTS_MODE": ["tts", "mode"],
        "CXO_TTS_MODEL_DIR": ["tts", "model_dir"],
        "CXO_TTS_DEVICE": ["tts", "device"],
        "CXO_TTS_REMOTE_URL": ["tts", "remote_url"],
        "CXO_LLM_PROVIDER": ["llm", "provider"],
        "CXO_LLM_HOST": ["llm", "host"],
        "CXO_LLM_MODEL": ["llm", "model"],
        "CXO_LLM_API_KEY": ["llm", "api_key"],
        "CXO_DATABASE_PATH": ["database", "path"],
        "CXO_MEMORY_VECTOR_BACKEND": ["memory", "vector_backend"],
        "CXO_ASR_URL": ["services", "asr", "url"],
        "CXO_TTS_URL": ["services", "tts", "url"],
        "CXO_INDEX_TTS_URL": ["services", "index_tts", "url"],
        "CXO_LOG_LEVEL": ["logging", "level"],
        "CXO_GRAPH_DATABASE_PATH": ["graph", "database_path"],
        "CXO_GRAPH_ENABLED": ["graph", "enabled"],
    }

    for env_key, path_parts in _env_mappings.items():
        value = os.getenv(env_key)
        if value is None:
            continue
        if not path_parts:
            continue

        if env_key.endswith("_PORT"):
            value = int(value)
        elif env_key.endswith("_DEBUG"):
            value = value.lower() in ("true", "1", "yes")
        elif env_key.endswith("_WORKERS"):
            value = int(value)

        current = env_config
        for part in path_parts[:-1]:
            current = current.setdefault(part, {})
        current[path_parts[-1]] = value

    return env_config


class SystemConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    workers: int = 1


class CorsConfig(BaseModel):
    allow_origins: List[str] = Field(default_factory=lambda: ["*"])
    allow_methods: List[str] = Field(default_factory=lambda: ["*"])
    allow_headers: List[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = True


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors: CorsConfig = Field(default_factory=CorsConfig)


class ServiceConfig(BaseModel):
    url: str = ""
    http_url: Optional[str] = None
    timeout: int = 30
    pool_size: int = 5
    reconnect_interval: int = 5
    heartbeat_interval: int = 30


class EmotionVoiceConfig(BaseModel):
    ref_audio: str = ""
    ref_text: str = ""


class TTSServiceConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    url: str = "http://127.0.0.1:5000"
    timeout: int = 120
    ref_audio_path: str = ""
    ref_text: str = ""
    model_type: str = "F5-TTS"
    speed: float = 1.0
    cross_fade_duration: float = 0.15
    emotion_enabled: bool = True
    effects_enabled: bool = True
    emotion_voices: Dict[str, EmotionVoiceConfig] = Field(default_factory=dict)
    default_emotion_intensity: float = 0.5
    emotion_templates: Optional[Dict[str, Any]] = None


class AudioConfig(BaseModel):
    effects_dir: str = "data/effects"


class IndexTTSConfig(BaseModel):
    url: str = "http://127.0.0.1:8004"
    timeout: int = 180
    enabled: bool = True
    auto_stop_delay: int = 300
    start_command: str = "python -m index_tts.app --port 8004 --host 0.0.0.0"
    working_dir: str = "index-tts"


class AdaptivePollingConfig(BaseModel):
    enabled: bool = True
    offset_ms: int = 0
    window_size: int = 3
    min_interval_ms: int = 50
    max_interval_ms: int = 2000


class SenseVoiceStreamingConfig(BaseModel):
    chunk_size: int = 1600
    hop_size: int = 800
    look_back: int = 8000


class ServicesConfig(BaseModel):
    asr: ServiceConfig = Field(default_factory=ServiceConfig)
    tts: TTSServiceConfig = Field(default_factory=TTSServiceConfig)
    audio: Optional[AudioConfig] = None
    index_tts: Optional[IndexTTSConfig] = None
    control_service_url: Optional[str] = None
    adaptive_polling: Optional[AdaptivePollingConfig] = None
    sensevoice_streaming: Optional[SenseVoiceStreamingConfig] = None


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: Optional[str] = None
    max_bytes: int = 10485760
    backup_count: int = 5


class LLMConfig(BaseModel):
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "qwen3:latest"
    temperature: float = 0.7
    max_tokens: int = 32768
    stream: bool = True
    api_key: Optional[str] = None


class ModelConfig(BaseModel):
    provider: str = "ollama"
    host: str = "http://localhost:11434"
    port: int = 8000
    model: str = "qwen3:latest"
    temperature: float = 0.7
    max_tokens: int = 0
    timeout: int = 60
    api_key: Optional[str] = None

    def get_model_config(self, model_type: str) -> "ModelConfig":
        return self


class ModelsConfig(BaseModel):
    main: ModelConfig = Field(default_factory=ModelConfig)
    summary: ModelConfig = Field(default_factory=lambda: ModelConfig(max_tokens=131072))
    memory: ModelConfig = Field(default_factory=lambda: ModelConfig(max_tokens=131072))
    defaults: Dict[str, str] = Field(default_factory=lambda: {"summary": "main", "memory": "main"})

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
        return self.main


class WeaviateConfig(BaseModel):
    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    embedded: bool = False
    vector_size: int = 768
    schema_class: str = "CXOMemory"
    api_key: Optional[str] = None


class MemoryConfig(BaseModel):
    decay_enabled: bool = True
    batch_interval: int = 3600
    permanent_threshold: float = 0.95
    max_short_term_age_days: int = 7
    max_long_term_age_days: int = 365
    vector_enabled: bool = True
    vector_backend: str = "weaviate"
    weaviate: WeaviateConfig = Field(default_factory=WeaviateConfig)
    archive_enabled: bool = True
    dedup_threshold: float = 0.85
    archive_compression_enabled: bool = True


class DatabaseConfig(BaseModel):
    path: str = "data/cxo.db"
    memories_db: str = "data/memories.db"
    sessions_db: str = "data/sessions.db"
    acp_db: str = "data/acp"
    pool_size: int = 10
    max_overflow: int = 20

    @property
    def url(self) -> str:
        return f"sqlite+aiosqlite:///{self.path}"


class ACPDiscoveryConfig(BaseModel):
    enabled: bool = True
    discovery_port: int = 9999
    broadcast_port: int = 9998
    broadcast_address: str = "255.255.255.255"
    interval: int = 30


class ACPConnectionConfig(BaseModel):
    port: int = 10000
    heartbeat_interval: int = 10
    timeout: int = 30


class ACPGroupConfig(BaseModel):
    port: int = 10001
    max_members: int = 50


class ACPConfig(BaseModel):
    enabled: bool = True
    agent_id: str = "cxo-agent-001"
    agent_name: str = "CX-O Agent"
    discovery: ACPDiscoveryConfig = Field(default_factory=ACPDiscoveryConfig)
    connection: ACPConnectionConfig = Field(default_factory=ACPConnectionConfig)
    group: ACPGroupConfig = Field(default_factory=ACPGroupConfig)


class CORSConfig(BaseModel):
    enabled: bool = True
    origins: List[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = True


class ContextConfig(BaseModel):
    max_messages: int = 100
    summary_threshold: int = 20
    window_size: int = 10
    enable_summary: bool = True


class VectorConfig(BaseModel):
    enabled: bool = True
    host: str = "localhost"
    port: int = 6333
    collection_name: str = "cxo_memories"
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768
    api_key: Optional[str] = None


class ASRConfig(BaseModel):
    mode: str = "remote"
    model_dir: str = "SenseVoiceSmall"
    device: str = "cuda"
    remote_url: str = "http://127.0.0.1:8001"
    language: str = "auto"


class OrpheusConfig(BaseModel):
    """Orpheus TTS（基于 vLLM 的 OpenAI 兼容 API）配置。"""
    url: str = "http://127.0.0.1:5060"
    model: str = "canopylabs/orpheus-multilingual-research-release"
    voice: str = "tara"
    timeout: int = 60
    flashinfer_enabled: bool = True
    sample_rate: int = 24000


class TTSConfig(BaseModel):
    mode: str = "remote"
    model_dir: str = "F5TTS_v1_Base"
    device: str = "cuda"
    remote_url: str = "http://127.0.0.1:5000"
    ref_audio_path: str = ""
    ref_text: str = ""
    speed: float = 1.0
    cross_fade_duration: float = 0.15
    emotion_enabled: bool = True
    effects_enabled: bool = True
    emotion_refs_dir: str = "data/voice_refs/emotions"
    transitions_dir: str = "data/voice_refs/transitions"
    transition_enabled: bool = True
    transition_text: str = "嗯，"
    # Orpheus TTS 配置段（mode == "orpheus" 时生效）
    orpheus: OrpheusConfig = Field(default_factory=OrpheusConfig)


class VoiceWorkstationConfig(BaseModel):
    url: str = "http://127.0.0.1:8200"
    enabled: bool = True


class RateLimitConfig(BaseModel):
    enabled: bool = True


class GraphWeaviateConfig(BaseModel):
    url: str = "http://localhost:8080"
    api_key: Optional[str] = None
    vector_dim: int = 384
    batch_size: int = 100
    ef_construction: int = 128
    max_connections: int = 16


class GraphEmbeddingConfig(BaseModel):
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 32
    device: str = "cpu"
    cache_folder: Optional[str] = None


class GraphConfigSection(BaseModel):
    enabled: bool = True
    database_path: str = "data/graph.db"
    auto_create_schema: bool = True
    pool_size: int = 10
    timeout: int = 30
    weaviate: GraphWeaviateConfig = Field(default_factory=GraphWeaviateConfig)
    embedding: GraphEmbeddingConfig = Field(default_factory=GraphEmbeddingConfig)


class CXFCConfig(BaseModel):
    enabled: bool = True
    heartbeat_timeout: int = 30
    heartbeat_check_interval: int = 10
    discovery_enabled: bool = True
    discovery_port: int = 9996
    broadcast_port: int = 9997
    auto_connect_on_startup: bool = True
    storage_path: str = "data/cxfc_plugins.db"


class MemoryLimitsConfig(BaseModel):
    max_memories: int = 30
    min_score_threshold: float = 0.15
    hybrid_search_limit: int = 30
    hybrid_search_min_score: float = 0.15
    vector_min_score: float = 0.3
    inject_memories_count: int = 20
    rag_search_limit: int = 20
    entity_extract_max_content: int = 8000
    max_entities: int = 50
    max_relationships: int = 100
    entity_candidates: int = 50
    search_memories_limit: int = 10
    search_similar_threshold: float = 0.5
    search_similar_limit: int = 10
    chat_history_limit: int = 50
    memory_logs_limit: int = 100
    search_all_limit: int = 10


class ContextLimitsConfig(BaseModel):
    max_messages: int = 500
    window_size: int = 50
    summary_threshold: int = 100
    max_history: int = 500
    conversation_max_messages: int = 100
    conversation_recent_window: int = 20
    summarizer_max_topics: int = 15
    summarizer_max_key_points: int = 15
    chat_context_limit: int = 10


class FirewallLimitsConfig(BaseModel):
    max_message_length: int = 10000
    max_messages_per_second: float = 5.0
    max_messages_per_minute: int = 100
    duplicate_threshold: int = 3
    duplicate_window_seconds: int = 30


class FrontendLimitsConfig(BaseModel):
    max_upload_size_mb: int = 500
    max_chat_images: int = 20
    avatar_min_width: int = 100
    avatar_max_width: int = 1200
    temperature_max: int = 5
    speed_max: int = 3


class LimitsConfig(BaseModel):
    memory: MemoryLimitsConfig = Field(default_factory=MemoryLimitsConfig)
    context: ContextLimitsConfig = Field(default_factory=ContextLimitsConfig)
    firewall: FirewallLimitsConfig = Field(default_factory=FirewallLimitsConfig)
    frontend: FrontendLimitsConfig = Field(default_factory=FrontendLimitsConfig)


class UnifiedConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    system: SystemConfig = Field(default_factory=SystemConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    services: ServicesConfig = Field(default_factory=ServicesConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    acp: ACPConfig = Field(default_factory=ACPConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    vector: VectorConfig = Field(default_factory=VectorConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    voice_workstation: VoiceWorkstationConfig = Field(default_factory=VoiceWorkstationConfig)
    graph: GraphConfigSection = Field(default_factory=GraphConfigSection)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    cxfc: CXFCConfig = Field(default_factory=CXFCConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)


class Settings:
    _instance: Optional["Settings"] = None
    _config: Optional[UnifiedConfig] = None
    _config_path: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._config = self._load_config()

    @classmethod
    def reset(cls):
        cls._instance = None
        cls._config = None
        cls._config_path = None

    @property
    def config(self) -> UnifiedConfig:
        return self._config

    def _get_config_path(self) -> Path:
        config_env = os.getenv(f"{ENV_PREFIX}CONFIG")
        if config_env:
            return Path(config_env)
        return Path(__file__).parent.parent / "config.json"

    def _load_config(self) -> UnifiedConfig:
        config_path = self._get_config_path()
        self._config_path = str(config_path)

        file_config: Dict[str, Any] = {}
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                file_config = json.load(f)

        env_config = get_env_config()
        merged_config = deep_merge(file_config, env_config)

        return UnifiedConfig(**merged_config)

    def reload_config(self):
        self._config = self._load_config()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if self._config is not None and hasattr(self._config, name):
            return getattr(self._config, name)
        raise AttributeError(f"'Settings' has no attribute '{name}'")


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_config() -> UnifiedConfig:
    return get_settings().config


def save_config(config: UnifiedConfig) -> None:
    settings = get_settings()
    config_path = Path(settings._config_path or settings._get_config_path())

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=4, ensure_ascii=False)

    settings._config = config


def reload_config() -> UnifiedConfig:
    settings = get_settings()
    settings.reload_config()
    return settings.config


def get_service_url(service_name: str) -> str:
    config = get_config()
    service_config = getattr(config.services, service_name, None)
    if service_config is None:
        raise ValueError(f"Unknown service: {service_name}")
    return service_config.url
