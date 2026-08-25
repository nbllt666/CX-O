"""
CX-O-SERVER 统一配置模块
合并 gateway/config.py、config/settings.py 和原 server/config.py 为单一 Pydantic 配置模型
从 config.json 读取，支持 CXO_ 前缀环境变量覆盖
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from server.core.utils import deep_merge


ENV_PREFIX = "CXO_"

# 项目根（CX-O-SERVER），基于文件位置解析，避免依赖运行时工作目录。
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_data_path(path: str) -> str:
    """将相对数据路径解析为项目根绝对路径（绝对路径原样返回）。

    供数据库/存储路径配置归一化使用，消除对运行时工作目录的依赖。
    """
    p = Path(path)
    return str(_PROJECT_ROOT / p) if not p.is_absolute() else path


def get_env_config() -> Dict[str, Any]:
    """从 CXO_ 前缀环境变量读取配置，生成按路径映射的配置字典。

    用于合并到文件配置之上，支持 CXO_ 前缀环境变量覆盖。
    """
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
        "CXO_ASR_VOICEPRINT_ENABLED": ["asr", "voiceprint_enabled"],
        "CXO_ASR_SPK_SIM_THRESHOLD": ["asr", "spk_sim_threshold"],
        "CXO_ASR_SPK_MODEL": ["asr", "spk_model"],
        "CXO_TTS_MODE": ["tts", "mode"],
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
        "CXO_ADMIN_ENABLED": ["admin", "enabled"],
        "CXO_ADMIN_BIND": ["admin", "bind"],
        "CXO_ADMIN_TLS_ENABLED": ["admin", "tls_enabled"],
        "CXO_ADMIN_RATE_LIMIT_PER_SEC": ["admin", "rate_limit_per_sec"],
        "CXO_ADMIN_CX_A_ENDPOINT": ["admin", "cx_a_endpoint"],
        "CXO_CLUSTER_ENABLED": ["cluster", "enabled"],
        "CXO_CLUSTER_NODE_NAME": ["cluster", "node_name"],
        "CXO_CLUSTER_SECRET": ["cluster", "cluster_secret"],
        "CXO_CLUSTER_ROLE": ["cluster", "role"],
        "CXO_CLUSTER_TRANSPORT": ["cluster", "transport"],
        "CXO_CLUSTER_BIND": ["cluster", "bind"],
        # vision_enhanced 节（视觉增强视频叙事记忆，默认关闭，零侵入）
        "CXO_VISION_ENABLED": ["vision_enhanced", "enabled"],
        "CXO_VISION_BUFFER_RETENTION_SEC": ["vision_enhanced", "buffer_retention_sec"],
        "CXO_VISION_DIFF_THRESHOLD": ["vision_enhanced", "diff_threshold"],
        "CXO_VISION_EVENT_COOLDOWN_SEC": ["vision_enhanced", "event_cooldown_sec"],
        "CXO_VISION_MAX_CLIPS_PER_HOUR": ["vision_enhanced", "max_clips_per_hour"],
        "CXO_VISION_PRE_ROLL_SEC": ["vision_enhanced", "pre_roll_sec"],
        "CXO_VISION_POST_ROLL_SEC": ["vision_enhanced", "post_roll_sec"],
        "CXO_VISION_CLIP_MAX_SEC": ["vision_enhanced", "clip_max_sec"],
        "CXO_VISION_NARRATIVE_MEMORY_ENABLED": ["vision_enhanced", "narrative_memory_enabled"],
        "CXO_VISION_TEMPORAL_FUSION_ENABLED": ["vision_enhanced", "temporal_fusion_enabled"],
        "CXO_VISION_OCR_KEYFRAME_ENABLED": ["vision_enhanced", "ocr_keyframe_enabled"],
        "CXO_VISION_REQUIRE_VLLM": ["vision_enhanced", "require_vllm"],
        # meeting 节（多 Agent 语音会议协调器，默认关闭，零侵入）
        "CXO_MEETING_ENABLED": ["meeting", "enabled"],
        "CXO_MEETING_MAX_AGENTS": ["meeting", "max_agents"],
        "CXO_MEETING_ARBITER_MODEL": ["meeting", "arbiter_model"],
        "CXO_MEETING_DEFAULT_MODE": ["meeting", "default_mode"],
        "CXO_MEETING_TOKEN_HOLD_TIMEOUT_SEC": ["meeting", "token_hold_timeout_sec"],
        "CXO_MEETING_RELAY_PAUSE_SEC": ["meeting", "relay_pause_sec"],
        "CXO_MEETING_BACKCHANNEL_ENABLED": ["meeting", "backchannel_enabled"],
        "CXO_MEETING_BACKCHANNEL_VOLUME": ["meeting", "backchannel_volume"],
        "CXO_MEETING_TRANSCRIPT_MAX_TURNS": ["meeting", "transcript_max_turns"],
        "CXO_MEETING_TRANSCRIPT_SUMMARY": ["meeting", "transcript_summary"],
        "CXO_MEETING_AGENT_INTERRUPT_ENABLED": ["meeting", "agent_interrupt_enabled"],
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
        # vision_enhanced 节类型转换：CXO_VISION_ 前缀键按目标字段名做 bool/int/float 转换
        # （不落入上方的 _PORT/_DEBUG/_WORKERS 通用后缀逻辑，布尔默认 closed）
        if env_key.startswith(f"{ENV_PREFIX}VISION_") and path_parts:
            field = path_parts[-1]
            if field == "enabled" or field.endswith("_enabled") or field == "require_vllm":
                value = value.lower() in ("true", "1", "yes")
            elif field == "diff_threshold":
                value = float(value)
            elif field in (
                "buffer_retention_sec", "event_cooldown_sec", "max_clips_per_hour",
                "pre_roll_sec", "post_roll_sec", "clip_max_sec",
            ):
                value = int(value)

        current = env_config
        for part in path_parts[:-1]:
            current = current.setdefault(part, {})
        # meeting 节类型转换（CXO_MEETING_ 前缀键按目标字段名做 bool/int/float 转换）
        if env_key.startswith(f"{ENV_PREFIX}MEETING_") and path_parts:
            field = path_parts[-1]
            if field in ("enabled", "backchannel_enabled", "transcript_summary", "agent_interrupt_enabled"):
                value = value.lower() in ("true", "1", "yes")
            elif field in ("token_hold_timeout_sec", "relay_pause_sec", "backchannel_volume"):
                value = float(value)
            elif field in ("max_agents", "transcript_max_turns"):
                value = int(value)
        current[path_parts[-1]] = value

    return env_config


class SystemConfig(BaseModel):
    """系统服务配置节：服务监听主机、端口、调试开关、日志级别与工作进程数。"""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    workers: int = 1


class CorsConfig(BaseModel):
    """CORS 跨域配置节：允许的源、方法与请求头及凭据开关。"""

    allow_origins: List[str] = Field(default_factory=lambda: ["*"])
    allow_methods: List[str] = Field(default_factory=lambda: ["*"])
    allow_headers: List[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = True


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors: CorsConfig = Field(default_factory=CorsConfig)


class ServiceConfig(BaseModel):
    """通用服务连接配置节：服务地址、超时、连接池与心跳间隔。"""

    url: str = ""
    http_url: Optional[str] = None
    timeout: int = 30
    pool_size: int = 5
    reconnect_interval: int = 5
    heartbeat_interval: int = 30


class TTSServiceConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    url: str = "http://127.0.0.1:5000"
    timeout: int = 120
    ref_audio_path: str = ""
    ref_text: str = ""
    model_type: str = "qwen3"
    speed: float = 1.0
    cross_fade_duration: float = 0.15
    emotion_enabled: bool = True
    effects_enabled: bool = True
    default_emotion_intensity: float = 0.5
    emotion_templates: Optional[Dict[str, Any]] = None


class SenseVoiceStreamingConfig(BaseModel):
    """SenseVoice 流式识别配置节：分块大小、跳跃长度与回看长度。"""

    chunk_size: int = 1600
    hop_size: int = 800
    look_back: int = 8000


class ServicesConfig(BaseModel):
    asr: ServiceConfig = Field(default_factory=ServiceConfig)
    tts: TTSServiceConfig = Field(default_factory=TTSServiceConfig)
    control_service_url: Optional[str] = None
    sensevoice_streaming: Optional[SenseVoiceStreamingConfig] = None


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: Optional[str] = None
    max_bytes: int = 10485760
    backup_count: int = 5


class LLMConfig(BaseModel):
    """LLM 配置节：模型提供方、服务地址、模型名与采样参数。"""

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
    top_p: Optional[float] = None  # 核采样参数，None 表示不启用
    api_key: Optional[str] = None

    def get_model_config(self, model_type: str) -> "ModelConfig":
        """按模型类型返回自身（单模型场景恒返回当前实例）。"""
        return self


class ModelsConfig(BaseModel):
    """多模型集合配置节：主/摘要/记忆模型及类型映射默认值。

    显式配置优先：当 ``models.<type>`` 节在配置文件中显式存在时直接使用该节；
    否则按 ``defaults`` 映射跟随（默认 summary/memory 跟随 main）。
    """

    main: ModelConfig = Field(default_factory=ModelConfig)
    summary: ModelConfig = Field(default_factory=lambda: ModelConfig(max_tokens=131072))
    memory: ModelConfig = Field(default_factory=lambda: ModelConfig(max_tokens=131072))
    defaults: Dict[str, str] = Field(default_factory=lambda: {"summary": "main", "memory": "main"})

    _explicit: Set[str] = PrivateAttr(default_factory=set)

    def _set_explicit(self, types: Iterable[str]) -> None:
        """记录配置文件中显式存在的模型节（供 defaults 跟随降级判断）。"""
        self._explicit = set(types)

    def resolve_target(self, model_type: str) -> str:
        """返回该模型类型实际使用的配置节名。

        显式配置的模型返回自身；否则按 ``defaults`` 映射回退（未知类型回退到 main）。
        """
        model_type = model_type.lower()
        if model_type in ("main", "summary", "memory") and model_type not in self._explicit:
            return self.defaults.get(model_type, "main")
        return model_type

    def get_model_config(self, model_type: str) -> ModelConfig:
        """按模型类型返回对应的模型配置。

        显式配置优先；未显式配置时遵循 ``defaults`` 映射，未知类型回退到主模型。
        """
        return getattr(self, self.resolve_target(model_type), self.main)


class WeaviateConfig(BaseModel):
    host: str = "localhost"
    port: int = 8080
    grpc_port: int = 50051
    embedded: bool = False
    vector_size: int = 1024
    schema_class: str = "CXOMemory"
    api_key: Optional[str] = None


class MemoryConfig(BaseModel):
    """记忆配置节：衰减策略、向量检索、嵌入模型与归档开关。"""

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

    @model_validator(mode="after")
    def _resolve_absolute_paths(self):
        """将数据库路径归一化为项目根绝对路径，消除 CWD 依赖。"""
        for field in ("path", "memories_db", "sessions_db", "acp_db"):
            value = getattr(self, field)
            if value:
                setattr(self, field, _resolve_data_path(value))
        return self

    @property
    def url(self) -> str:
        return f"sqlite+aiosqlite:///{self.path}"


class ACPDiscoveryConfig(BaseModel):
    """ACP 发现配置节：LAN 发现开关、发现/广播端口与广播间隔。"""

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
    """ACP 群组配置节：群组端口与最大成员数。"""

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
    """向量检索配置节：启用开关、服务地址、集合名与嵌入参数。"""

    enabled: bool = True
    host: str = "localhost"
    port: int = 6333
    collection_name: str = "cxo_memories"
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 1024
    api_key: Optional[str] = None


class ASRConfig(BaseModel):
    mode: str = "remote"
    model_dir: str = "SenseVoiceSmall"
    device: str = "cuda"
    # 2026-08-25 与容器统一：ASR 容器单次识别与声纹 REST 均监听 8005
    # （此前默认 8001 与 compose 端口不一致，纯默认配置下不可达；CX-O-SERVER/config.json 已显式覆盖为 8005）
    remote_url: str = "http://127.0.0.1:8005"
    # WebSocket streaming URL（方案B：SenseVoice 加 WS 接口）
    # 当 mode="remote" 时，streaming 接口优先使用 ws_url 而非 remote_url
    # 默认指向 sensevoice 容器映射的 8005 端口
    ws_url: str = "ws://127.0.0.1:8005/ws/asr/stream"
    language: str = "auto"
    # 声纹识别配置（Task 5/6）：声纹服务总开关、相似度阈值与声纹模型
    voiceprint_enabled: bool = True
    spk_sim_threshold: float = 0.65
    spk_model: str = "iic/speech_campplus_sv_zh-cn_16k-common"


class TTSConfig(BaseModel):
    """TTS 配置节：Qwen3 统一编排的参数与参考音频资产目录。

    F5-TTS / Orpheus 旧引擎已随 Qwen3 迁移彻底移除（Task 7），不再保留
    mode/model_dir/orpheus 等旧字段。
    """

    mode: str = "remote"
    device: str = "cuda"
    remote_url: str = "http://127.0.0.1:5000"
    ref_audio_path: str = ""
    ref_text: str = ""
    speed: float = 1.0
    cross_fade_duration: float = 0.15
    emotion_enabled: bool = True
    effects_enabled: bool = True
    transitions_dir: str = "data/voice_refs/transitions"
    transition_enabled: bool = True
    transition_text: str = "嗯，"
    # 统一参考音频资产存储（Task 3）：资产元数据索引与音频文件的持久化目录
    ref_audio_assets_dir: str = "data/ref_audio_assets"
    # 外部文件注册时允许读取的额外目录（相对项目根解析）。空列表时仅允许 assets_dir。
    allowed_ref_audio_dirs: List[str] = Field(default_factory=list)
    # 参考音频单文件大小上限（MB）
    max_ref_audio_size_mb: int = 50

    @model_validator(mode="after")
    def _resolve_data_paths(self):
        for field in ("transitions_dir", "ref_audio_assets_dir"):
            value = getattr(self, field)
            if value:
                setattr(self, field, _resolve_data_path(value))
        if self.allowed_ref_audio_dirs:
            self.allowed_ref_audio_dirs = [
                _resolve_data_path(d) for d in self.allowed_ref_audio_dirs
            ]
        return self


class Qwen3TTSVLLMConfig(BaseModel):
    """Qwen3 TTS vLLM VoiceDesign 运行时配置节（voicedesign 运行时，OpenAI 兼容 /v1/audio/speech）。

    对应 qwen3_tts_config.schema.json 的 vllm 段（配置段名保持 vllm，运行时名为
    voicedesign，由 Provider 内部映射）。vLLM 私有参数（task_type 等）仅存在于
    Provider 与配置契约，不泄漏到前端 request/response 协议。
    vLLM 承载 VoiceDesign 任务（task_type=VoiceDesign）：无参考音频时的日常/情感合成。
    """

    base_url: str = "http://127.0.0.1:8091"
    model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    task_type: str = "VoiceDesign"
    timeout_seconds: float = 60
    sample_rate: int = 24000
    # 该配置段对应的 Provider 运行时名（与 config.json 中 runtime 段保持一致口径）
    runtime_name: str = "voicedesign"


class Qwen3TTSCosyVoiceConfig(BaseModel):
    """CosyVoice3-0.5B 克隆运行时配置节（cosyvoice 运行时，带参考音频的语音克隆与情感合成）。

    对应 qwen3_tts_config.schema.json 的 cosyvoice 段。base_url 为空则禁用克隆能力。
    请求携带 refs 时 Provider 首选路由本运行时；不可用/超时/非法响应时降级 qwen3_base。
    """

    base_url: str = "http://127.0.0.1:8094"
    model: str = "Fun-CosyVoice3-0.5B-2512"
    timeout_seconds: float = 120
    sample_rate: int = 24000


class Qwen3TTSBaseConfig(BaseModel):
    """Qwen3-TTS Base 降级运行时配置节（qwen3_base 运行时，主运行时不可用时的全局兜底）。

    对应 qwen3_tts_config.schema.json 的 qwen3_base 段。CosyVoice/VoiceDesign
    不可用/超时/非法响应时 Provider 降级到本运行时（vLLM，OpenAI 兼容）。
    """

    base_url: str = "http://127.0.0.1:8093"
    model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    timeout_seconds: float = 120
    sample_rate: int = 24000


class Qwen3TTSDefaultConfig(BaseModel):
    """Qwen3 TTS 默认合成参数配置节（voice/language/output_format/speed）。"""

    voice: str = "vivian"
    language: str = ""
    output_format: str = "wav"
    speed: float = 1.0


class Qwen3TTSEmotionConfig(BaseModel):
    """Qwen3 TTS 情感指令配置节（开关、长度上限、中性回退）。"""

    enabled: bool = True
    max_length: int = 200
    fallback_neutral: bool = True


class Qwen3TTSLegacyConfig(BaseModel):
    """旧引擎移除配置节：旧引擎配置不再作为可选引擎，命中时映射 LEGACY_ENGINE_REMOVED。"""

    return_removed_error: bool = True


class Qwen3TTSConfig(BaseModel):
    """统一 Qwen3 TTS 配置节：运行时选择（voicedesign 首选/带 refs 时路由 cosyvoice，
    失败降级 qwen3_base）与各子配置。

    对应 qwen3_tts_config.schema.json。缺失字段由 Pydantic default 补齐。
    """

    enabled: bool = True
    runtime: str = "vllm"
    vllm: Qwen3TTSVLLMConfig = Field(default_factory=Qwen3TTSVLLMConfig)
    cosyvoice: Qwen3TTSCosyVoiceConfig = Field(default_factory=Qwen3TTSCosyVoiceConfig)
    qwen3_base: Qwen3TTSBaseConfig = Field(default_factory=Qwen3TTSBaseConfig)
    default: Qwen3TTSDefaultConfig = Field(default_factory=Qwen3TTSDefaultConfig)
    emotion_instruction: Qwen3TTSEmotionConfig = Field(default_factory=Qwen3TTSEmotionConfig)
    legacy_engine_removed: Qwen3TTSLegacyConfig = Field(default_factory=Qwen3TTSLegacyConfig)


class GraphWeaviateConfig(BaseModel):
    """图数据库 Weaviate 配置节：服务地址、向量维度与批量构建参数。"""

    url: str = "http://localhost:8080"
    api_key: Optional[str] = None
    vector_dim: int = 384
    batch_size: int = 100
    ef_construction: int = 128
    max_connections: int = 16


class GraphEmbeddingConfig(BaseModel):
    """图嵌入配置节：嵌入模型、批大小、设备与缓存目录。"""

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

    @model_validator(mode="after")
    def _resolve_data_paths(self):
        if self.database_path:
            self.database_path = _resolve_data_path(self.database_path)
        return self


class CXFCConfig(BaseModel):
    """CXFC 插件配置节：心跳、发现端口、启动自动连接与插件存储路径。"""

    enabled: bool = True
    heartbeat_timeout: int = 30
    heartbeat_check_interval: int = 10
    discovery_enabled: bool = True
    discovery_port: int = 9996
    broadcast_port: int = 9997
    auto_connect_on_startup: bool = True
    storage_path: str = "data/cxfc_plugins.db"

    @model_validator(mode="after")
    def _resolve_data_paths(self):
        if self.storage_path:
            self.storage_path = _resolve_data_path(self.storage_path)
        return self


class AdminTokenConfig(BaseModel):
    """管理面令牌配置：token 与权限分级（readonly / operator / superadmin）。"""

    token: str
    level: str = "readonly"


class AdminConfig(BaseModel):
    """管理面（CX-A）配置节：总开关与监听地址、TLS、分级 token、防重放与限流、主动注册。"""

    enabled: bool = False
    bind: str = "127.0.0.1"
    tls_enabled: bool = False
    tokens: List[AdminTokenConfig] = Field(default_factory=list)
    request_id_ttl_sec: int = 300
    rate_limit_per_sec: float = 20
    cx_a_endpoint: str = ""
    register_heartbeat_sec: int = 15

    def token_level(self, token: str) -> Optional[str]:
        """返回匹配 token 的权限等级（不匹配返回 None）。"""
        for t in self.tokens:
            if t.token == token:
                return t.level
        return None


class ClusterWitnessConfig(BaseModel):
    """见证节点（tiebreaker）配置：2 节点集群无法形成多数派时仲裁，仅仲裁不承载灵魂。"""

    endpoint: str = ""
    secret: str = ""


class ClusterConfig(BaseModel):
    """哨兵集群配置节：节点身份、共享密钥、种子对等、心跳/快照参数与传输。"""

    enabled: bool = False
    node_name: str = ""
    cluster_secret: str = ""
    peers: List[str] = Field(default_factory=list)
    role: str = "standby"
    peer_heartbeat_interval_sec: int = 5
    peer_timeout_sec: float = 15
    miss_threshold: int = 3
    snapshot_interval_sec: int = 300
    sync_units: List[str] = Field(default_factory=lambda: ["memory", "persona", "config", "session", "ref_audio"])
    transport: str = "https"
    bind: str = "0.0.0.0"
    witness: ClusterWitnessConfig = Field(default_factory=ClusterWitnessConfig)


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
    """对话上下文相关的消息数量与窗口限制配置节。"""

    max_messages: int = 500
    window_size: int = 50
    summary_threshold: int = 100
    max_history: int = 500
    conversation_max_messages: int = 100
    conversation_recent_window: int = 20
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
    """各类限制配置聚合节：记忆、上下文、防火墙与前端限制。"""

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

    @model_validator(mode="after")
    def _resolve_data_paths(self):
        for field in ("session_storage_dir", "log_storage_dir"):
            value = getattr(self, field)
            if value:
                setattr(self, field, _resolve_data_path(value))
        return self


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

    @model_validator(mode="after")
    def _resolve_data_paths(self):
        for field in ("rubric_path", "audit_log_path"):
            value = getattr(self, field)
            if value:
                setattr(self, field, _resolve_data_path(value))
        return self


class CXOTunerConfig(BaseModel):
    """CXO-Tuner evolution 配置节：CX-O 主后端到 CXO-Tuner 自适应微调服务的集成出口。

    对应 public/config_template/cxo_tuner_config.schema.json 中 CX-O 侧集成字段
    （host / timeout / quality_reject_threshold / auto_push / lora_enabled）。
    缺失字段由 Pydantic default 补齐；越界字段在 _auto_fill_radix_config 中
    回退默认值（timeout 1-300、quality_reject_threshold 0-1）。
    """

    enabled: bool = False  # 是否启用（evolution 集成出口）
    host: str = "http://127.0.0.1:8300"  # CXO-Tuner 服务基础 URL
    timeout: int = 10  # 客户端请求超时（秒），取值范围 1-300
    quality_reject_threshold: float = 0.3  # 反馈质量拒绝阈值，0-1（对照 decision_core）
    auto_push: bool = False  # 是否自动推送反馈/会话历史到 Tuner
    lora_enabled: bool = False  # 是否通过 vLLM LoRA 端点路由应用适配器

    model_config = ConfigDict(protected_namespaces=())


class VisionEnhancedConfig(BaseModel):
    """视觉增强视频叙事记忆配置节（vision_enhanced，默认关闭，零侵入）。

    对应 public/config_template/radix_config.json 的 vision_enhanced 段。
    后端叙事记忆功能仅在 enabled=true 时生效；其余开关按下述默认值。缺失字段由
    Pydantic default 补齐；越界数值字段在 _auto_fill_radix_config 中回退默认值
    （buffer_retention_sec 5-300、clip_max_sec 2-120、diff_threshold 0.01-1、
    event_cooldown_sec 1-300、max_clips_per_hour 1-1000）。
    """

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = False  # 总开关，默认关闭
    buffer_retention_sec: int = 30  # 事件前缓冲池保留时长（秒），5-300
    diff_threshold: float = 0.08  # 视觉差分变化阈值，0.01-1
    event_cooldown_sec: int = 15  # 相邻事件最小间隔（秒），1-300
    max_clips_per_hour: int = 12  # 每小时最大片段数，1-1000
    pre_roll_sec: int = 3  # 事件前预滚动缓冲（秒）
    post_roll_sec: int = 6  # 事件后滚动缓冲（秒）
    clip_max_sec: int = 10  # 单片段最大时长（秒），2-120
    narrative_memory_enabled: bool = True  # 是否启用叙事记忆回写
    temporal_fusion_enabled: bool = False  # 是否启用跨时段时间融合
    ocr_keyframe_enabled: bool = True  # 是否对关键帧做 OCR
    require_vllm: bool = True  # 是否要求 vLLM 后端（false 可用于降级/调试）


class DanmakuSourceConfig(BaseModel):
    """互动空间观众弹幕源采集配置（type=none 时零侵入，不启动采集器）。

    对应《会议重定位为互动空间》spec 的观众弹幕通道。type 枚举 none|bilibili|rdf：
    - none：不启用弹幕源
    - bilibili：连接 bilibili 直播弹幕（host/port/room_id）
    - rdf：通用 WebSocket 文本行弹幕（websocket_url）
    type 不在枚举时由 _auto_fill_meeting_config 回退 none。
    """

    model_config = ConfigDict(protected_namespaces=())

    type: str = "none"  # 弹幕源类型（none|bilibili|rdf），默认 none，零侵入
    host: str = ""  # 弹幕源主机（bilibili 用）
    port: int = 0  # 弹幕源端口（bilibili 用）
    room_id: str = ""  # 直播间号（bilibili 用）
    websocket_url: str = ""  # 通用 WebSocket 地址（rdf 用）


class MeetingConfig(BaseModel):
    """多 Agent 互动空间协调器配置节（meeting，默认 enabled=false，零侵入）。

    对应《CX-O 多 Agent 语音会议协调器》§12 配置系统扩展（并承接《会议重定位为
    互动空间》T4.1 字段扩展）。缺失字段由 Pydantic default 补齐；越界数值字段在
    _auto_fill_meeting_config 中回退默认值（max_agents 1-10、token_hold_timeout_sec
    1-600、relay_pause_sec 0-5、backchannel_volume 0-1、transcript_max_turns 1-200、
    speech_rate 0-1）。
    """

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = False  # 总开关，默认关闭，零侵入
    max_agents: int = 5  # 单房间 agent 上限
    arbiter_model: str = "independent"  # 主答模型名（LLM 驱动主答选择）
    default_mode: str = "moderator"  # 插话模型名/策略名（空用内置）
    token_hold_timeout_sec: float = 30.0  # 令牌持有超时，防霸麦
    relay_pause_sec: float = 0.4  # agent 间接力停顿
    backchannel_enabled: bool = False  # 附和低音量开关（与协调器构造默认对齐）
    backchannel_volume: float = 0.2  # 附和音量（主发言的 20%）
    transcript_max_turns: int = 20  # 会议记录注入的最近轮数
    transcript_summary: bool = True  # 更早记录是否摘要压缩
    agent_interrupt_enabled: bool = False  # 是否允许 agent 打断 agent（进阶）
    audience_enabled: bool = False  # 观众席总开关，默认关零侵入
    danmaku_source: DanmakuSourceConfig = Field(default_factory=DanmakuSourceConfig)  # 观众弹幕源采集配置
    speech_rate: float = 0.3  # Agent 自发插话率 0-1
    agent_speech_prompt: str = ""  # 插话判断 prompt 模板，空用内置


class MCPServerConfig(BaseModel):
    """MCP 服务器配置节（P2-T1）：供配置驱动的 MCP 工具源自注册/自启。

    对应 config.json 的 ``mcp_servers`` 数组元素。字段与
    ``server.core.tools.mcp.MCPManager.add_server`` 入参对齐：
    name 必填；command/args/env/endpoint_url 可选；enabled 控制启动装配时
    是否自动 add_server + start_server（false 则跳过，不注册不启动）。
    """

    name: str
    command: str = ""
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    endpoint_url: str = "http://localhost:8600"
    enabled: bool = True


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
    # P2-T1: 配置驱动的 MCP 工具源自注册/自启（元素为 MCPServerConfig）
    mcp_servers: List[MCPServerConfig] = Field(default_factory=list)
    qwen3_tts: Qwen3TTSConfig = Field(default_factory=Qwen3TTSConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    # RADIX-Lite 新增 4 配置节（v1.1.0）
    distillation: DistillationConfig = Field(default_factory=DistillationConfig)
    multimodal_pipeline: MultimodalPipelineConfig = Field(default_factory=MultimodalPipelineConfig)
    radix: RadixConfig = Field(default_factory=RadixConfig)
    decision_core: DecisionCoreConfig = Field(default_factory=DecisionCoreConfig)
    evolution: CXOTunerConfig = Field(default_factory=CXOTunerConfig)
    # 视觉增强视频叙事记忆（默认关闭，零侵入）
    vision_enhanced: VisionEnhancedConfig = Field(default_factory=VisionEnhancedConfig)
    # CX-A 管理面 + 哨兵集群（默认 enabled=false，零侵入）
    admin: AdminConfig = Field(default_factory=AdminConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    # 多 Agent 语音会议协调器（默认 enabled=false，零侵入）
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)


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
        """重置全局单例，清空已加载的配置（主要用于测试）。"""
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

        config = UnifiedConfig(**merged_config)

        # 记录显式配置的模型节：仅当 models.<type> 显式存在时才解除 defaults 跟随，
        # 允许 summary/memory 独立配置不同模型（否则仍跟随 main）。
        models_section = merged_config.get("models")
        if isinstance(models_section, dict):
            explicit = [k for k in ("main", "summary", "memory") if k in models_section]
            config.models._set_explicit(explicit)

        return config

    def reload_config(self):
        self._config = self._load_config()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if self._config is not None and hasattr(self._config, name):
            return getattr(self._config, name)
        raise AttributeError(f"'Settings' has no attribute '{name}'")


def get_settings() -> Settings:
    """获取全局配置单例。

    直接收敛到 ``Settings()`` 的类级单例（``_instance``），不维护第二份模块级缓存。
    此前 ``get_settings()`` 用独立的模块全局 ``_settings`` 缓存，与 ``Settings()``
    的类级 ``_instance`` 构成双缓存：``Settings.reset()`` 只清类级、不清模块级，
    reset 后 ``get_settings()`` 会返回持有旧配置的过期实例，与 ``Settings()`` 分叉。
    收敛后唯一真相源是类级单例，reset 即重建，二者永远一致。
    """
    return Settings()


def get_config() -> UnifiedConfig:
    return get_settings().config


def save_config(config: UnifiedConfig) -> None:
    """将配置对象写入 config.json 并更新内存缓存。"""
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
    """获取指定外部服务的 URL，未知服务名抛出 ValueError。"""
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

    # ---- vision_enhanced 节（视觉增强视频叙事记忆）越界检查 ----
    ve = user_config.setdefault("vision_enhanced", {})
    if "buffer_retention_sec" in ve:
        v = ve["buffer_retention_sec"]
        if not isinstance(v, (int, float)) or v < 5 or v > 300:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.buffer_retention_sec={v} 越界（5-300），回退默认值 30")
            ve["buffer_retention_sec"] = 30
    if "clip_max_sec" in ve:
        v = ve["clip_max_sec"]
        if not isinstance(v, (int, float)) or v < 2 or v > 120:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.clip_max_sec={v} 越界（2-120），回退默认值 10")
            ve["clip_max_sec"] = 10
    if "diff_threshold" in ve:
        v = ve["diff_threshold"]
        if not isinstance(v, (int, float)) or v < 0.01 or v > 1:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.diff_threshold={v} 越界（0.01-1），回退默认值 0.08")
            ve["diff_threshold"] = 0.08
    if "event_cooldown_sec" in ve:
        v = ve["event_cooldown_sec"]
        if not isinstance(v, (int, float)) or v < 1 or v > 300:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.event_cooldown_sec={v} 越界（1-300），回退默认值 15")
            ve["event_cooldown_sec"] = 15
    if "max_clips_per_hour" in ve:
        v = ve["max_clips_per_hour"]
        if not isinstance(v, (int, float)) or v < 1 or v > 1000:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.max_clips_per_hour={v} 越界（1-1000），回退默认值 12")
            ve["max_clips_per_hour"] = 12
    # pre_roll_sec / post_roll_sec：无硬性上限，仅校验为非负数值，非法回退默认 3 / 6
    if "pre_roll_sec" in ve:
        v = ve["pre_roll_sec"]
        if not isinstance(v, (int, float)) or v < 0:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.pre_roll_sec={v} 非法，回退默认值 3")
            ve["pre_roll_sec"] = 3
    if "post_roll_sec" in ve:
        v = ve["post_roll_sec"]
        if not isinstance(v, (int, float)) or v < 0:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.post_roll_sec={v} 非法，回退默认值 6")
            ve["post_roll_sec"] = 6

    # ---- radix 节（遗留兼容，无越界检查，仅记录 auto_fill）----
    user_config.setdefault("radix", {})

    # ---- evolution 节（CXO-Tuner evolution 集成出口）越界检查 ----
    ev = user_config.setdefault("evolution", {})
    if "timeout" in ev:
        t = ev["timeout"]
        if not isinstance(t, int) or t < 1 or t > 300:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: evolution.timeout={t} 越界（1-300），回退默认值 10")
            ev["timeout"] = 10
    if "quality_reject_threshold" in ev:
        v = ev["quality_reject_threshold"]
        if not isinstance(v, (int, float)) or v < 0 or v > 1:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: evolution.quality_reject_threshold={v} 越界（0-1），回退默认值 0.3")
            ev["quality_reject_threshold"] = 0.3

    # ---- meeting 节（多 Agent 语音会议协调器）越界检查 ----
    mt = user_config.setdefault("meeting", {})
    if "max_agents" in mt:
        v = mt["max_agents"]
        if not isinstance(v, int) or v < 1 or v > 10:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: meeting.max_agents={v} 越界（1-10），回退默认值 5")
            mt["max_agents"] = 5
    if "token_hold_timeout_sec" in mt:
        v = mt["token_hold_timeout_sec"]
        if not isinstance(v, (int, float)) or v < 1 or v > 600:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: meeting.token_hold_timeout_sec={v} 越界（1-600），回退默认值 30")
            mt["token_hold_timeout_sec"] = 30
    if "relay_pause_sec" in mt:
        v = mt["relay_pause_sec"]
        if not isinstance(v, (int, float)) or v < 0 or v > 5:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: meeting.relay_pause_sec={v} 越界（0-5），回退默认值 0.4")
            mt["relay_pause_sec"] = 0.4
    if "backchannel_volume" in mt:
        v = mt["backchannel_volume"]
        if not isinstance(v, (int, float)) or v < 0 or v > 1:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: meeting.backchannel_volume={v} 越界（0-1），回退默认值 0.2")
            mt["backchannel_volume"] = 0.2
    if "transcript_max_turns" in mt:
        v = mt["transcript_max_turns"]
        if not isinstance(v, int) or v < 1 or v > 200:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: meeting.transcript_max_turns={v} 越界（1-200），回退默认值 20")
            mt["transcript_max_turns"] = 20
    if "speech_rate" in mt:
        v = mt["speech_rate"]
        if not isinstance(v, (int, float)) or v < 0 or v > 1:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: meeting.speech_rate={v} 越界（0-1），回退默认值 0.3")
            mt["speech_rate"] = 0.3
    if isinstance(mt.get("danmaku_source"), dict) and "type" in mt["danmaku_source"]:
        ds_type = mt["danmaku_source"]["type"]
        if ds_type not in ("none", "bilibili", "rdf"):
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: meeting.danmaku_source.type={ds_type} 不在 none|bilibili|rdf，回退默认值 none")
            mt["danmaku_source"]["type"] = "none"

    logger.info("CONFIG_AUTO_FILL_APPLIED: RADIX-Lite 配置 auto_fill + 越界检查完成")

    return user_config
