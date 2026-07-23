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
        "CXO_ASR_WS_URL": ["asr", "ws_url"],
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
        "CXO_MEMORY_EMBEDDING_PROVIDER": ["memory", "embedding_provider"],
        "CXO_MEMORY_EMBEDDING_MODEL": ["memory", "embedding_model"],
        "CXO_MEMORY_EMBEDDING_API_BASE": ["memory", "embedding_api_base"],
        "CXO_MEMORY_EMBEDDING_API_KEY": ["memory", "embedding_api_key"],
        "CXO_ASR_URL": ["services", "asr", "url"],
        "CXO_TTS_URL": ["services", "tts", "url"],
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
    embedding_provider: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_api_base: str = ""
    embedding_api_key: Optional[str] = None
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
    # WebSocket streaming URL（方案B：SenseVoice 加 WS 接口）
    # 当 mode="remote" 时，streaming 接口优先使用 ws_url 而非 remote_url
    # 默认指向 sensevoice 容器映射的 8005 端口
    ws_url: str = "ws://127.0.0.1:8005/ws/asr/stream"
    language: str = "auto"


class OrpheusConfig(BaseModel):
    """Orpheus TTS（基于 vLLM 的 OpenAI 兼容 API）配置。"""
    url: str = "http://127.0.0.1:5060"
    model: str = "canopylabs/orpheus-multilingual-research-release"
    # 默认音色：长乐（官方多语言版中文女声，温柔自然）
    # 备选：白芷（女声清晰）、tara（英文女声，仅英文场景）
    voice: str = "长乐"
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


# ============================================================================
# RADIX-Lite 配置节（v1.1.0 新增，对应 public/config_template/radix_config.json）
# 蒸馏服务 / 多模态管线 / 决策核心 / 遗留兼容
# ============================================================================


class DistillationConfig(BaseModel):
    """RADIX-Lite 蒸馏服务配置（9 状态机参数）。

    对应 radix_config.json 的 distillation_service 节。
    CX-O-SERVER 主路由注册，端口 8000（不再独立 8011）。
    """
    host: str = "127.0.0.1"
    port: int = 8000  # CX-O-SERVER 主服务端口，distillation 作为子路由注册
    max_turns: int = 4  # 默认最大蒸馏轮次，取值 1-6
    session_timeout_seconds: int = 1800  # 会话超时（秒），60-7200
    session_storage_dir: str = "data/distillation_sessions"
    log_storage_dir: str = "data/distillation_logs"  # 决策审计日志目录
    main_backend_url: str = "http://127.0.0.1:8000"  # 调用主后端 API（如 write_with_decision）
    # OBS-6 方案 C：LLM 质量评估配置（自然 S_REJECT 可达性修复）
    # 启用后 _estimate_quality_score 优先调用 LLM 评估；失败或禁用时回退启发式（基础分 0.4）
    quality_llm_enabled: bool = True  # 是否启用 LLM 质量评估
    quality_llm_model: str = ""  # LLM 模型名，空字符串表示从 llm 段继承默认模型
    quality_llm_timeout_seconds: int = 30  # LLM 调用超时（秒），5-120


class MultimodalPipelineConfig(BaseModel):
    """MultimodalPipeline 多模态管线配置。

    对应 radix_config.json 的 multimodal_pipeline 节。
    CX-O 扩展：video/audio 走 vLLM 原生解码（仅当 LLM provider=vllm 时启用）。
    """
    model_config = ConfigDict(protected_namespaces=())

    worker_pool_size: int = 4  # 1-16
    task_timeout_seconds: int = 120  # 10-600，OCR/vision 推理可能较慢
    enabled_modalities: List[str] = Field(
        default_factory=lambda: ["text", "character_card", "image", "video", "audio"]
    )
    ocr_engine: str = "paddleocr"
    ocr_language: str = "ch"  # ch=中英文，en=英文，japan=日文
    vision_degraded_fallback: bool = True  # vision 不可用时降级为仅 OCR
    vision_base_url: str = "http://127.0.0.1:8080"  # vision 模型服务 URL（可与 vLLM 主模型同实例）
    vision_model: str = ""  # vision 模型名，空字符串表示不启用 vision（仅 OCR）
    vision_timeout_seconds: int = 300  # vision 推理超时
    vllm_native_enabled: bool = True  # CX-O 扩展：是否启用 vLLM 原生视频/音频解码


class RadixConfig(BaseModel):
    """RADIX-Lite 遗留配置兼容（端口 8011 等历史参数）。

    CX-O 已将 RADIX 子服务合并到主后端 8000，此配置节仅保留兼容字段，
    用于读取旧版配置文件或控制 legacy_parser 回退开关。
    """
    legacy_parser_enabled: bool = True  # parser.py 回退开关，true=走原有解析逻辑
    legacy_port: int = 8011  # CXHMS 历史 RADIX 端口，CX-O 已合并到 8000，仅保留兼容字段


class DecisionCoreConfig(BaseModel):
    """DecisionCore 决策核心配置（6 决策点 rubric 默认值）。

    对应 radix_config.json 的 decision_core 节。
    D1_LOCATION / D2_METADATA / D3_ASK_USER / D4_REDISTILL / D5_CROSS_VALIDATE / D6_REJECT
    """
    importance_threshold_permanent: float = 0.7  # 0-1，永久记忆重要性阈值
    quality_reject_threshold: float = 0.3  # 0-1，质量拒绝阈值，低于此值触发 D6_REJECT
    max_redistill_turns: int = 2  # 0-6，最大再次蒸馏轮次
    ask_user_confidence_threshold: float = 0.4  # 0-1，追问置信度阈值
    cross_validate_sources: List[str] = Field(default_factory=list)  # 跨源验证数据源列表
    rejected_content_retention_days: int = 30  # 1-90，拒绝内容保留天数
    system_prompt_fallback_enabled: bool = True  # LLM 置信度极低时回退 system_prompt
    rubric_path: str = "data/agents.json"  # 决策 rubric 路径
    audit_log_path: str = "data/distillation_logs/"  # 审计日志路径


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
    vector: VectorConfig = Field(default_factory=VectorConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    graph: GraphConfigSection = Field(default_factory=GraphConfigSection)
    cxfc: CXFCConfig = Field(default_factory=CXFCConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    # RADIX-Lite 新增 4 配置节（v1.1.0）
    distillation: DistillationConfig = Field(default_factory=DistillationConfig)
    multimodal_pipeline: MultimodalPipelineConfig = Field(default_factory=MultimodalPipelineConfig)
    radix: RadixConfig = Field(default_factory=RadixConfig)
    decision_core: DecisionCoreConfig = Field(default_factory=DecisionCoreConfig)


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

        # RADIX-Lite 配置 auto_fill + 越界回退（rules-3 §三 配置契约 auto_fill）
        merged_config = _auto_fill_radix_config(merged_config)

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


# ============================================================================
# RADIX-Lite 配置 auto_fill + 越界回退（rules-3 §三 配置契约 auto_fill）
# ============================================================================


def _auto_fill_radix_config(user_config: Dict[str, Any]) -> Dict[str, Any]:
    """RADIX-Lite 配置 auto_fill 默认值 + 越界字段回退默认值。

    对应 public/config_template/radix_config.json 的 auto_fill 契约：
      - 缺失字段：Pydantic BaseModel 的 Field(default_factory=...) 已自然补齐，
        本函数不重复补齐，仅在日志中标记 CONFIG_AUTO_FILL_APPLIED（信息级）
      - 越界字段：检查取值范围，越界则回退默认值并 log warning（CONFIG_FIELD_OUT_OF_RANGE）
      - JSON 解析失败：由 _load_config 上游 try-except 处理，本函数不介入

    调用时机：Settings._load_config 中 deep_merge 后、UnifiedConfig 实例化前。

    Args:
        user_config: 合并 env + file 后的配置 dict

    Returns:
        处理后的配置 dict（原 dict 被原地修改并返回）
    """
    import logging
    logger = logging.getLogger(__name__)

    # ---- distillation 节越界检查 ----
    distillation = user_config.setdefault("distillation", {})
    if "max_turns" in distillation:
        mt = distillation["max_turns"]
        if not isinstance(mt, int) or mt < 1 or mt > 6:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: distillation.max_turns={mt} 越界（1-6），回退默认值 4")
            distillation["max_turns"] = 4
    if "session_timeout_seconds" in distillation:
        s = distillation["session_timeout_seconds"]
        if not isinstance(s, int) or s < 60 or s > 7200:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: distillation.session_timeout_seconds={s} 越界（60-7200），回退默认值 1800")
            distillation["session_timeout_seconds"] = 1800
    if "port" in distillation:
        p = distillation["port"]
        if not isinstance(p, int) or p < 1024 or p > 65535:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: distillation.port={p} 越界（1024-65535），回退默认值 8000")
            distillation["port"] = 8000

    # ---- multimodal_pipeline 节越界检查 ----
    mm = user_config.setdefault("multimodal_pipeline", {})
    if "worker_pool_size" in mm:
        w = mm["worker_pool_size"]
        if not isinstance(w, int) or w < 1 or w > 16:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: multimodal_pipeline.worker_pool_size={w} 越界（1-16），回退默认值 4")
            mm["worker_pool_size"] = 4
    if "task_timeout_seconds" in mm:
        t = mm["task_timeout_seconds"]
        if not isinstance(t, int) or t < 10 or t > 600:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: multimodal_pipeline.task_timeout_seconds={t} 越界（10-600），回退默认值 120")
            mm["task_timeout_seconds"] = 120
    if "enabled_modalities" in mm:
        valid_modalities = {"text", "character_card", "image", "video", "audio"}
        em = mm["enabled_modalities"]
        if not isinstance(em, list) or not all(isinstance(x, str) for x in em):
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: multimodal_pipeline.enabled_modalities={em} 非字符串列表，回退默认值 5 模态")
            mm["enabled_modalities"] = ["text", "character_card", "image", "video", "audio"]
        else:
            invalid = set(em) - valid_modalities
            if invalid:
                logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: multimodal_pipeline.enabled_modalities 含未知模态 {invalid}，过滤掉")
                mm["enabled_modalities"] = [x for x in em if x in valid_modalities] or ["text"]

    # ---- decision_core 节越界检查 ----
    dc = user_config.setdefault("decision_core", {})
    if "importance_threshold_permanent" in dc:
        v = dc["importance_threshold_permanent"]
        if not isinstance(v, (int, float)) or v < 0 or v > 1:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: decision_core.importance_threshold_permanent={v} 越界（0-1），回退默认值 0.7")
            dc["importance_threshold_permanent"] = 0.7
    if "quality_reject_threshold" in dc:
        v = dc["quality_reject_threshold"]
        if not isinstance(v, (int, float)) or v < 0 or v > 1:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: decision_core.quality_reject_threshold={v} 越界（0-1），回退默认值 0.3")
            dc["quality_reject_threshold"] = 0.3
    if "max_redistill_turns" in dc:
        v = dc["max_redistill_turns"]
        if not isinstance(v, int) or v < 0 or v > 6:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: decision_core.max_redistill_turns={v} 越界（0-6），回退默认值 2")
            dc["max_redistill_turns"] = 2
    if "ask_user_confidence_threshold" in dc:
        v = dc["ask_user_confidence_threshold"]
        if not isinstance(v, (int, float)) or v < 0 or v > 1:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: decision_core.ask_user_confidence_threshold={v} 越界（0-1），回退默认值 0.4")
            dc["ask_user_confidence_threshold"] = 0.4
    if "rejected_content_retention_days" in dc:
        v = dc["rejected_content_retention_days"]
        if not isinstance(v, int) or v < 1 or v > 90:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: decision_core.rejected_content_retention_days={v} 越界（1-90），回退默认值 30")
            dc["rejected_content_retention_days"] = 30

    # ---- radix 节（遗留兼容，无越界检查，仅记录 auto_fill）----
    user_config.setdefault("radix", {})

    logger.info("CONFIG_AUTO_FILL_APPLIED: RADIX-Lite 配置 auto_fill + 越界检查完成")

    return user_config
