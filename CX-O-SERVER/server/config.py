"""
CX-O-SERVER 统一配置模块
合并 gateway/config.py、config/settings.py 和原 server/config.py 为单一 Pydantic 配置模型
从 config.json 读取，支持 CXO_ 前缀环境变量覆盖
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from server.core.utils import deep_merge

logger = logging.getLogger(__name__)

ENV_PREFIX = "CXO_"

# 配置保存/重载的串行化锁（RLock 可重入，供 save_config / reload_config /原子写共享）。
# 防止并发首实例化、并发 save 与 reload 对 _config 的读写竞态，保证写盘 file 与
# 内存缓存永远一致。
_CONFIG_SAVE_LOCK = threading.RLock()

# 最近一次成功解析的文件配置快照（内存层），供 config.json 内容损坏时回退，
# 避免损坏文件导致启动流程崩溃。
_last_known_config: Optional[Dict[str, Any]] = None

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
        # vision_enhanced 帧过滤器（spec add-vlm-frame-filter-face-match）
        "CXO_VISION_FRAME_FILTER_ENABLED": ["vision_enhanced", "frame_filter_enabled"],
        "CXO_VISION_FRAME_FILTER_VLM_ENDPOINT": ["vision_enhanced", "filter_vlm_endpoint"],
        "CXO_VISION_FRAME_FILTER_VLM_MODEL": ["vision_enhanced", "filter_vlm_model"],
        "CXO_VISION_FRAME_FILTER_CONTEXT_MESSAGES": ["vision_enhanced", "filter_context_messages"],
        "CXO_VISION_FRAME_FILTER_TIMEOUT_SECONDS": ["vision_enhanced", "filter_timeout_seconds"],
        "CXO_VISION_FRAME_FILTER_FAIL_MODE": ["vision_enhanced", "filter_fail_mode"],
        # face_match 节（人脸档案匹配，默认关闭，零侵入）
        "CXO_FACE_ENABLED": ["face_match", "enabled"],
        "CXO_FACE_PROVIDER": ["face_match", "provider"],
        "CXO_FACE_ENDPOINT": ["face_match", "endpoint"],
        "CXO_FACE_SIM_THRESHOLD": ["face_match", "sim_threshold"],
        "CXO_FACE_MAX_FACES_PER_FRAME": ["face_match", "max_faces_per_frame"],
        "CXO_FACE_MODEL_ROOT": ["face_match", "model_root"],
        "CXO_FACE_STORE_PATH": ["face_match", "store_path"],
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
        # executor 有界 IO / 并发限流节
        "CXO_EXECUTOR_IO_POOL_SIZE": ["executor", "io_pool_size"],
        "CXO_EXECUTOR_DANMAKU_CONCURRENCY": ["executor", "danmaku_concurrency"],
        "CXO_EXECUTOR_INTERRUPT_CONCURRENCY": ["executor", "interrupt_concurrency"],
        # executor 语音并发治理节（Module 0 语音多会话并发）
        "CXO_EXECUTOR_ASR_INFER_WORKERS": ["executor", "asr_infer_workers"],
        "CXO_EXECUTOR_SPK_ENGINE_WORKERS": ["executor", "spk_engine_workers"],
        "CXO_EXECUTOR_SPK_INFLIGHT_MAX": ["executor", "spk_inflight_max"],
        "CXO_EXECUTOR_TTS_CONCURRENCY": ["executor", "tts_concurrency"],
        "CXO_EXECUTOR_TTS_BACKPRESSURE_MODE": ["executor", "tts_backpressure_mode"],
        "CXO_EXECUTOR_ASR_RECV_QUEUE_MAXSIZE": ["executor", "asr_recv_queue_maxsize"],
    }

    for env_key, path_parts in _env_mappings.items():
        value = os.getenv(env_key)
        if value is None:
            continue
        if not path_parts:
            continue

        if env_key.endswith("_PORT") or env_key.endswith("_WORKERS"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                # A4 修复：坏环境变量不应阻断整个服务启动，记日志后跳过该键用默认值
                logger.warning(
                    f"环境变量 {env_key}={value!r} 不是合法整数，忽略该键并使用默认值"
                )
                continue
        elif env_key.endswith("_DEBUG"):
            value = value.lower() in ("true", "1", "yes")
        # vision_enhanced 节类型转换：CXO_VISION_ 前缀键按目标字段名做 bool/int/float 转换
        # （不落入上方的 _PORT/_DEBUG/_WORKERS 通用后缀逻辑，布尔默认 closed）
        if env_key.startswith(f"{ENV_PREFIX}VISION_") and path_parts:
            field = path_parts[-1]
            if field == "enabled" or field.endswith("_enabled") or field == "require_vllm":
                value = value.lower() in ("true", "1", "yes")
            elif field in ("diff_threshold", "filter_timeout_seconds"):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    logger.warning(
                        f"环境变量 {env_key}={value!r} 不是合法数字，忽略该键并使用默认值"
                    )
                    continue
            elif field in (
                "buffer_retention_sec", "event_cooldown_sec", "max_clips_per_hour",
                "pre_roll_sec", "post_roll_sec", "clip_max_sec",
                "filter_context_messages",
            ):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    logger.warning(
                        f"环境变量 {env_key}={value!r} 不是合法整数，忽略该键并使用默认值"
                    )
                    continue

        current = env_config
        for part in path_parts[:-1]:
            current = current.setdefault(part, {})
        # meeting 节类型转换（CXO_MEETING_ 前缀键按目标字段名做 bool/int/float 转换）
        if env_key.startswith(f"{ENV_PREFIX}MEETING_") and path_parts:
            field = path_parts[-1]
            if field in ("enabled", "backchannel_enabled", "transcript_summary", "agent_interrupt_enabled"):
                value = value.lower() in ("true", "1", "yes")
            elif field in ("token_hold_timeout_sec", "relay_pause_sec", "backchannel_volume"):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    logger.warning(
                        f"环境变量 {env_key}={value!r} 不是合法数字，忽略该键并使用默认值"
                    )
                    continue
            elif field in ("max_agents", "transcript_max_turns"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    logger.warning(
                        f"环境变量 {env_key}={value!r} 不是合法整数，忽略该键并使用默认值"
                    )
                    continue
        # executor 语音并发节类型转换（整数/模式，避免 env 覆盖成字符串）
        if env_key.startswith(f"{ENV_PREFIX}EXECUTOR_") and path_parts:
            field = path_parts[-1]
            if field in ("asr_infer_workers", "spk_engine_workers", "spk_inflight_max",
                         "tts_concurrency", "asr_recv_queue_maxsize",
                         "danmaku_concurrency", "interrupt_concurrency"):
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    # A4 修复：坏环境变量不应让 Pydantic 启动崩溃，
                    # 记日志后跳过该键并使用默认值（对齐 VISION/MEETING 分支模式）
                    logger.warning(
                        f"环境变量 {env_key}={value!r} 不是合法整数，忽略该键并使用默认值"
                    )
                    continue
            elif field == "tts_backpressure_mode":
                value = str(value)
        # face_match 节类型转换（CXO_FACE_ 前缀键按目标字段名做 bool/int/float 转换，
        # 对齐 VISION/MEETING/EXECUTOR 分支模式，避免 env 覆盖成字符串）
        if env_key.startswith(f"{ENV_PREFIX}FACE_") and path_parts:
            field = path_parts[-1]
            if field == "enabled":
                value = value.lower() in ("true", "1", "yes")
            elif field == "sim_threshold":
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    logger.warning(
                        f"环境变量 {env_key}={value!r} 不是合法数字，忽略该键并使用默认值"
                    )
                    continue
            elif field == "max_faces_per_frame":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    logger.warning(
                        f"环境变量 {env_key}={value!r} 不是合法整数，忽略该键并使用默认值"
                    )
                    continue
        current[path_parts[-1]] = value

    return env_config


class SystemConfig(BaseModel):
    """系统服务配置节：服务监听主机、端口、调试开关、日志级别与工作进程数。"""

    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    log_level: str = "INFO"
    workers: int = 1
    # 跨进程单 leader 锁文件路径（多 worker 后台服务去重用）。空串（默认）表示
    # 自动落到 <项目根>/data/leader.lock；显式设置可覆盖。默认 workers=1 时零侵入。
    leader_lock_path: str = ""


class ExecutorConfig(BaseModel):
    """进程级有界 IO / 并发限流配置节（Module 0 消除事件循环阻断）。

    - ``io_pool_size``：async 热路径同步 sqlite/文件 IO/CPU 段的共享 IO 线程池大小。
      ``<=0``（默认）表示自动取值 ``min(32, (os.cpu_count() or 4) + 4)``，
      保持默认行为零侵入，不改变既有并发上限。
    - ``danmaku_concurrency``：直播弹幕 fire-and-forget 反馈任务的信号量上限，
      超限丢弃，防止任务无限堆积。
    - ``interrupt_concurrency``：ASR Partial 打断判定后台任务的信号量上限，超限丢弃。

    语音链路多会话并发治理（默认与现状一致，零侵入，不破坏既有测试）：
    - ``asr_infer_workers``：ASR embedded 推理线程池大小（现状 ``max_workers=2``），
      允许配置放大。
    - ``spk_engine_workers``：流式引擎共享线程池大小（ASR 推理 + 声纹共用，
      现状 ``max_workers=4``），允许配置放大。
    - ``spk_inflight_max``：声纹 in-flight 后台任务上限（现状 ``SPK_INFLIGHT_MAX=2``）。
    - ``tts_concurrency``：TTS ``synthesize``/``synthesize_stream`` 统一 in-flight
      信号量上限（默认取一个不破坏现状的较大数 8）。
    - ``tts_backpressure_mode``：``"wait"`` 超限排队等待 / ``"drop"`` 超限丢弃。
    - ``asr_recv_queue_maxsize``：ASR WS 接收队列有界上限；``0``（默认）表示无界，
      与现状一致；``>0`` 时消费者慢于生产者由 ``put`` 自然背压，避免无界堆积。
    """

    io_pool_size: int = 0
    danmaku_concurrency: int = 8
    interrupt_concurrency: int = 8
    # ---- 语音链路并发治理（默认与现状一致，零侵入）----
    asr_infer_workers: int = 2
    spk_engine_workers: int = 4
    spk_inflight_max: int = 2
    tts_concurrency: int = 8
    tts_backpressure_mode: str = "wait"
    asr_recv_queue_maxsize: int = 0


class CorsConfig(BaseModel):
    """CORS 跨域配置节（gateway.cors，当前无中间件消费点，保留作配置兼容）。

    默认值与顶层 CORSConfig 安全口径对齐（本机白名单 + 关闭凭据），
    防止未来接入消费点时复刻"通配符 + 凭据反射"的不安全默认。
    """

    allow_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3100",
            "http://127.0.0.1:3100",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "null",
        ]
    )
    allow_methods: List[str] = Field(default_factory=lambda: ["*"])
    allow_headers: List[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = False


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

    # 与 server.api.routers.config._get_default_sensevoice_config 的缺省分块大小对齐
    # （1024），使单一真相源（UnifiedConfig）缺省值与 /config/sensevoice-streaming
    # 回退缺省保持一致，避免 1600/1024 冲突。
    chunk_size: int = 1024
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
    # CX-O-Dream 独立模型槽位：显式配置 models.dream 时梦境生成使用该节；未显式配置按 defaults 跟随 main
    dream: ModelConfig = Field(default_factory=ModelConfig)
    defaults: Dict[str, str] = Field(
        default_factory=lambda: {"summary": "main", "memory": "main", "dream": "main"}
    )

    _explicit: Set[str] = PrivateAttr(default_factory=set)

    def _set_explicit(self, types: Iterable[str]) -> None:
        """记录配置文件中显式存在的模型节（供 defaults 跟随降级判断）。"""
        self._explicit = set(types)

    def resolve_target(self, model_type: str) -> str:
        """返回该模型类型实际使用的配置节名。

        显式配置的模型返回自身；否则按 ``defaults`` 映射回退（未知类型回退到 main）。
        """
        model_type = model_type.lower()
        if model_type in ("main", "summary", "memory", "dream") and model_type not in self._explicit:
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
    """ACP 群组配置节：群组端口、最大成员数与每 agent 群组上限。"""

    port: int = 10001
    max_members: int = 50
    # #25（补充批注）: 每 agent 可持有的群组上限，此前 get_status 硬编码 10；
    # 配置契约缺省值自动补全（auto_fill），不破坏既有 config.json。
    max_groups: int = 10


class ACPConfig(BaseModel):
    enabled: bool = True
    agent_id: str = "cxo-agent-001"
    agent_name: str = "CX-O Agent"
    # 开放协议入口（/acp/receive、/acp/send/group）的独立协议 token，
    # 与 admin key 分离：缺省空 = 不校验（兼容既有外部 Agent 投递行为）；
    # 配置后调用方须携带同值 X-ACP-Key 头，否则 403（渐进启用，第11轮）。
    auth_token: str = ""
    discovery: ACPDiscoveryConfig = Field(default_factory=ACPDiscoveryConfig)
    connection: ACPConnectionConfig = Field(default_factory=ACPConnectionConfig)
    group: ACPGroupConfig = Field(default_factory=ACPGroupConfig)


class CORSConfig(BaseModel):
    """顶层 CORS 配置节（settings.cors，main.py 中间件消费）。

    安全默认值：本机来源白名单（3100=Vite dev、5173=Vite 默认、
    "null"=Electron file:// 渲染进程的 Origin 头），且默认关闭凭据。
    本应用无 Cookie 依赖（管理面走 x-api-key 头），credentials=False 无功能损失；
    局域网部署如需放行其它来源，请通过 config.json 的 cors.origins 显式配置。
    """

    enabled: bool = True
    origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:3100",
            "http://127.0.0.1:3100",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "null",
        ]
    )
    allow_credentials: bool = False


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
    host: str = "http://127.0.0.1:8310"  # CXO-Tuner 服务基础 URL（8310：8300 已归 CXO-ModelStation）
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
    event_cooldown_sec 1-300、max_clips_per_hour 1-1000、filter_context_messages
    1-20、filter_timeout_seconds 2-30、filter_fail_mode ∈ passthrough|discard）。
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
    # ---- 帧过滤器（spec add-vlm-frame-filter-face-match，VLM 帧过滤三态 filter/passthrough/discard，默认关闭零侵入）----
    frame_filter_enabled: bool = False  # 帧过滤器总开关，默认关闭
    filter_vlm_endpoint: str = ""  # 过滤 VLM 服务端点（OpenAI 兼容 base_url），空=未配置
    filter_vlm_model: str = ""  # 过滤 VLM 模型名，空=未配置
    filter_context_messages: int = 6  # 过滤请求携带的上下文消息条数，1-20，越界回退 6
    filter_timeout_seconds: float = 8.0  # 过滤 VLM 单帧调用超时（秒），2-30，越界回退 8.0
    filter_fail_mode: str = "passthrough"  # 过滤失败兜底模式（passthrough|discard），非法回退 passthrough


class FaceMatchConfig(BaseModel):
    """人脸档案匹配配置节（face_match，默认关闭，零侵入）。

    对应 public/config_template/radix_config.json 的 face_match 段与
    public/interface_stub/face.pyi 接口契约（spec add-vlm-frame-filter-face-match）。
    仅 enabled=true 时启用人脸注册/匹配；provider=local 使用本地模型目录推理，
    external 调用外部 HTTP 端点。缺失字段由 Pydantic default 补齐；越界字段在
    _auto_fill_radix_config 中回退默认值（sim_threshold 0.2-0.8、
    max_faces_per_frame 1-8、provider ∈ local|external）。
    """

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool = False  # 人脸匹配总开关，默认关闭
    provider: str = "local"  # 人脸识别提供方（local|external），非法回退 local
    endpoint: str = ""  # provider=external 时的服务端点，空=未配置
    sim_threshold: float = 0.45  # 人脸相似度匹配阈值，0.2-0.8，越界回退 0.45
    max_faces_per_frame: int = 4  # 单帧最多处理人脸数，1-8，越界回退 4
    model_root: str = ""  # provider=local 时的本地模型根目录，空=使用内置默认路径
    store_path: str = ""  # 人脸档案存储路径，空=使用内置默认路径


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


# ============================================================================
# CX-O 自主系统 / 梦境配置节（Task 6.2 配置迁入 UnifiedConfig）
# 字段逐一对照 server/autonomy/data/autonomy_config.json 与 dream_config.json
# （含默认值），启动时经 migrate_legacy_autonomy_configs 一次性导入并留档。
# 节模型与引擎侧 AutonomyConfig/DreamConfig 保持字段同构（契约镜像由
# tests/test_autonomy_builtin_migration.py 断言），此处独立定义避免
# config.py 在 import 期拉起 server.autonomy 包（其 __init__ 会导入 main.py）。
# 校验器（HH:MM 时间格式 / 枚举 / 动作白名单）与引擎侧 server/autonomy/config.py
# 语义一致，保证 PUT 校验口径与旧版完全相同。
# ============================================================================
# 时间字段格式（对齐 autonomy 契约 pattern ^([01]?[0-9]|2[0-3]):[0-5][0-9]$）
_AUTONOMY_HHMM_RE = re.compile(r"^([01]?[0-9]|2[0-3]):[0-5][0-9]$")
# 静默档窗口格式 HH:MM-HH:MM
_AUTONOMY_QUIET_WINDOW_RE = re.compile(
    r"^([01]?[0-9]|2[0-3]):[0-5][0-9]-([01]?[0-9]|2[0-3]):[0-5][0-9]$"
)
# 动作枚举（autonomy_action.schema.json，9 项）
AUTONOMY_ACTION_ENUM = [
    "sleep",
    "wait",
    "read_news",
    "search",
    "write_memory",
    "write_post",
    "start_live",
    "stop_live",
    "write_diary",
]


class AutonomySearchSection(BaseModel):
    """自主系统搜索子节（对齐 autonomy_config.json search）。"""

    model_config = ConfigDict(extra="forbid")
    mcp_server_name: str = "free-search-mcp"
    fallback_rss: bool = True


class AutonomyScheduleSection(BaseModel):
    """自主系统日程子节（对齐 autonomy_config.json schedule，HH:MM 校验）。"""

    model_config = ConfigDict(extra="forbid")
    wake_time: str = "08:00"
    sleep_time: str = "02:00"
    golden_start: str = "19:00"
    golden_end: str = "23:00"
    diary_time: str = "02:00"
    quiet_windows: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_times(self) -> "AutonomyScheduleSection":
        """时间字段 HH:MM 与静默档 HH:MM-HH:MM 校验（对齐引擎侧 ScheduleConfig）。"""
        for field_name in (
            "wake_time",
            "sleep_time",
            "golden_start",
            "golden_end",
            "diary_time",
        ):
            value = getattr(self, field_name)
            if not _AUTONOMY_HHMM_RE.match(value):
                raise ValueError(f"时间字段必须为 HH:MM 格式，收到 {value!r}")
        for window in self.quiet_windows:
            if not _AUTONOMY_QUIET_WINDOW_RE.match(window):
                raise ValueError(f"静默档必须为 HH:MM-HH:MM 格式，收到 {window!r}")
        return self


class AutonomyBudgetSection(BaseModel):
    """自主系统预算子节（对齐 autonomy_config.json budget）。"""

    model_config = ConfigDict(extra="forbid")
    daily_token_limit: int = 2000000
    daily_llm_calls_limit: int = 0
    cost_alert_threshold: float = 0.8
    overspend_mode: str = "sleep"

    @model_validator(mode="after")
    def _check_overspend_mode(self) -> "AutonomyBudgetSection":
        """overspend_mode 枚举校验（对齐引擎侧 BudgetConfig）。"""
        if self.overspend_mode not in ("sleep", "low_cost"):
            raise ValueError(f"overspend_mode 非法值 {self.overspend_mode!r}，可选 sleep/low_cost")
        return self


class AutonomyPermissionsSection(BaseModel):
    """自主系统权限子节（对齐 autonomy_config.json permissions）。"""

    model_config = ConfigDict(extra="forbid")
    allowed_actions: List[str] = Field(default_factory=list)
    blocked_actions: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_allowed_actions(self) -> "AutonomyPermissionsSection":
        """allowed_actions 白名单校验（对齐引擎侧 PermissionsConfig）。"""
        for action in self.allowed_actions:
            if action not in AUTONOMY_ACTION_ENUM:
                raise ValueError(f"allowed_actions 含非法 action {action!r}")
        return self


class AutonomySafetySection(BaseModel):
    """自主系统安全子节（对齐 autonomy_config.json safety）。"""

    model_config = ConfigDict(extra="forbid")
    content_gate_enabled: bool = True
    persona_check_enabled: bool = True
    post_rate_per_hour: int = 5
    user_online_sleep: bool = True
    leave_mode_authorize: bool = True


class AutonomySection(BaseModel):
    """CX-O-Autonomy 自主系统配置节（autonomy，迁移自 autonomy_config.json）。

    默认值与 server/autonomy/config.py AutonomyConfig 完全一致（enabled=False
    零侵入）；迁移时旧档缺失字段由 Pydantic 默认补齐。
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    enabled: bool = False
    auto_start: bool = False
    agent_id: str = "default"
    loop_interval_minutes: int = 15
    rss_sources: List[str] = Field(default_factory=list)
    search: AutonomySearchSection = Field(default_factory=AutonomySearchSection)
    schedule: AutonomyScheduleSection = Field(default_factory=AutonomyScheduleSection)
    budget: AutonomyBudgetSection = Field(default_factory=AutonomyBudgetSection)
    platforms: List[str] = Field(default_factory=list)
    permissions: AutonomyPermissionsSection = Field(
        default_factory=lambda: AutonomyPermissionsSection(
            allowed_actions=[
                "sleep",
                "wait",
                "read_news",
                "search",
                "write_memory",
                "write_post",
                "start_live",
                "stop_live",
                "write_diary",
            ]
        )
    )
    safety: AutonomySafetySection = Field(default_factory=AutonomySafetySection)
    store_path: str = ""


class DreamSleepConfirmationSection(BaseModel):
    """梦境休眠前 LLM 意图确认子节（对齐 dream_config.json sleep_confirmation）。"""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    model: str = "summary"
    timeout_sec: float = 10.0
    prompt_template: str = ""
    cooldown_seconds: int = 1800


class DreamPhysioSection(BaseModel):
    """梦境生理信号接入子节（对齐 dream_config.json physio）。

    store_raw_hr 沿用隐私红线 R6：原始心率禁止落盘，写 True 抛 ValueError。
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    backend: str = "noble"  # 信息性登记键（前端 Electron noble 采集，后端无对应实现）
    device_name_hint: str = ""
    device_fingerprint: Optional[str] = None
    scan_timeout_sec: int = 15
    reconnect_interval_sec: int = 30
    base_drop_ratio: float = 0.88
    base_drop_confirm_min: int = 5
    hr_stability_threshold: float = 6.0
    base_hr_learning: bool = True
    store_raw_hr: bool = False

    @model_validator(mode="after")
    def _check_store_raw_hr(self) -> "DreamPhysioSection":
        """store_raw_hr 强制 False（隐私红线 R6：原始心率禁止落盘）。"""
        if self.store_raw_hr:
            raise ValueError("store_raw_hr 必须为 False：原始心率禁止落盘（隐私红线 R6）")
        return self


class DreamTriggerSection(BaseModel):
    """梦境触发闸门子节（对齐 dream_config.json trigger）。

    默认值零回归：emotion_enabled=False 不做情绪查询；probability=1.0 恒命中。
    """

    model_config = ConfigDict(extra="forbid")
    emotion_enabled: bool = False
    emotion_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    emotion_window_hours: int = Field(default=24, ge=1)
    emotion_min_events: int = Field(default=1, ge=1)
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


class DreamSection(BaseModel):
    """CX-O-Dream 梦境引擎配置节（dream，迁移自 dream_config.json）。

    默认值与 server/autonomy/dream/config.py DreamConfig 完全一致
    （enabled=False 零侵入）；schedule 子节复用 AutonomyScheduleSection。
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())
    enabled: bool = False
    model: str = "summary"
    dream_temperature: float = 0.9
    candidates_per_session: int = 3
    material_window_days: int = 7
    max_material_items: int = 20
    min_lucidity: float = 0.3
    dream_ttl_hours: int = 72
    purge_threshold: float = 0.1
    confirmed_importance: float = 0.4
    surface_on_wake: bool = True
    surface_probability: float = 0.5
    max_surface_per_day: int = 1
    schedule: AutonomyScheduleSection = Field(default_factory=AutonomyScheduleSection)
    physio: DreamPhysioSection = Field(default_factory=DreamPhysioSection)
    trigger: DreamTriggerSection = Field(default_factory=DreamTriggerSection)
    sleep_confirmation: DreamSleepConfirmationSection = Field(
        default_factory=DreamSleepConfirmationSection
    )


class UnifiedConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    system: SystemConfig = Field(default_factory=SystemConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
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
    # 人脸档案匹配（默认关闭，零侵入，spec add-vlm-frame-filter-face-match）
    face_match: FaceMatchConfig = Field(default_factory=FaceMatchConfig)
    # CX-A 管理面 + 哨兵集群（默认 enabled=false，零侵入）
    admin: AdminConfig = Field(default_factory=AdminConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    # 多 Agent 语音会议协调器（默认 enabled=false，零侵入）
    meeting: MeetingConfig = Field(default_factory=MeetingConfig)
    # CX-O 自主系统 / 梦境引擎（Task 6.2 迁移自 server/autonomy/data/*.json，零侵入）
    autonomy: AutonomySection = Field(default_factory=AutonomySection)
    dream: DreamSection = Field(default_factory=DreamSection)


def atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    """原子写入 JSON 文件：写临时文件 → os.replace，避免写盘中途崩溃导致半写损坏。

    供本模块及业务路由（server.api.routers.* / service 层）复用。写入全程持有
    ``_CONFIG_SAVE_LOCK``，与 save_config / reload_config 串行化。临时文件 fsync 后
    再原子替换目标，保证任一时刻 config.json 要么是旧完整文件、要么是新完整文件，
    绝不出现损坏的中间态。

    Args:
        path: 目标文件路径（绝对路径）。
        data: 待序列化的 dict。
    """
    with _CONFIG_SAVE_LOCK:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Optional[str] = None
        try:
            fd, tmp_path = tempfile.mkstemp(
                dir=str(p.parent), prefix=f".{p.name}.", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, p)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def _backup_corrupt_config(config_path: Path) -> None:
    """将损坏的配置文件备份为 ``config.json.corrupt-<ts>``，便于事后排查。"""
    try:
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup = config_path.with_name(f"{config_path.name}.corrupt-{ts}")
        shutil.copyfile(config_path, backup)
        logger.warning(f"CONFIG_CORRUPT_BACKUP: 已备份损坏配置到 {backup}")
    except Exception as e:  # 备份失败不影响回退主流程
        logger.warning(f"备份损坏配置文件失败: {e}")


class Settings:
    _instance: Optional["Settings"] = None
    _config: Optional[UnifiedConfig] = None
    _config_path: Optional[str] = None
    # 单例首次实例化锁：防并发首次加载配置产生多个独立实例/重复读盘。
    _instance_lock = threading.RLock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        with self._instance_lock:
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
        global _last_known_config
        config_path = self._get_config_path()
        self._config_path = str(config_path)

        file_config: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
            except Exception as e:
                # 配置内容损坏/非法：备份损坏副本 → 回退最近一次成功内存快照或内置默认，
                # 绝不把解析异常抛回启动流程（允许服务带着默认/上次配置继续运行）。
                _backup_corrupt_config(config_path)
                if _last_known_config is not None:
                    file_config = _last_known_config
                    logger.error(
                        f"CONFIG_CORRUPT: 配置文件 {config_path} 解析失败（{e}），"
                        f"已备份损坏副本，回退最近一次成功快照。"
                    )
                else:
                    file_config = {}
                    logger.error(
                        f"CONFIG_CORRUPT: 配置文件 {config_path} 解析失败（{e}），"
                        f"已备份损坏副本，且无历史快照，回退内置默认配置。"
                    )

        env_config = get_env_config()
        merged_config = deep_merge(file_config, env_config)

        # RADIX-Lite 配置 auto_fill + 越界回退（rules-3 §三 配置契约 auto_fill）
        merged_config = _auto_fill_radix_config(merged_config)

        config = UnifiedConfig(**merged_config)

        # 记录显式配置的模型节：仅当 models.<type> 显式存在时才解除 defaults 跟随，
        # 允许 summary/memory/dream 独立配置不同模型（否则仍跟随 main）。
        models_section = merged_config.get("models")
        if isinstance(models_section, dict):
            explicit = [k for k in ("main", "summary", "memory", "dream") if k in models_section]
            config.models._set_explicit(explicit)

        # 更新内存快照（成功解析后），供下一次损坏时回退
        _last_known_config = file_config

        return config

    def reload_config(self):
        with _CONFIG_SAVE_LOCK:
            self._config = self._load_config()

    def save_config(self) -> None:
        """将当前配置实例写入磁盘并更新缓存（委托模块级 save_config）。

        历史缺陷：路由层曾以 ``settings.save_config()`` 调用，但 Settings 从未
        提供该实例方法，走 __getattr__ 抛 AttributeError → 配置保存恒 500 且不落盘。
        """
        if self._config is None:
            raise RuntimeError("配置尚未加载，无法保存")
        with _CONFIG_SAVE_LOCK:
            save_config(self._config)

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
    """将配置对象写入 config.json 并更新内存缓存（原子写 + 锁串行化）。"""
    settings = get_settings()
    config_path = Path(settings._config_path or settings._get_config_path())

    with _CONFIG_SAVE_LOCK:
        atomic_write_json(str(config_path), config.model_dump())
        settings._config = config


def reload_config() -> UnifiedConfig:
    settings = get_settings()
    with _CONFIG_SAVE_LOCK:
        settings.reload_config()
    return settings.config


# 旧配置文件所在目录：server/autonomy/data/（基于本文件绝对路径解析，禁止相对路径）。
_LEGACY_AUTONOMY_DATA_DIR = Path(__file__).resolve().parent / "autonomy" / "data"

# 迁移留档后缀：旧文件改名 <原名>.json.migrated 留档（不删除）。
_MIGRATED_SUFFIX = ".migrated"


def migrate_legacy_autonomy_configs(
    legacy_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """将旧 autonomy/dream 配置 JSON 一次性迁入 UnifiedConfig（Task 6.2，幂等）。

    迁移规则（spec「梦境/自主彻底集成」配置迁移 Scenario）：
    - 旧文件（autonomy_config.json / dream_config.json）存在且 UnifiedConfig
      对应节仍为全默认值 → 导入值 → save_config() → 旧文件改名 ``<原名>.migrated``
      留档（不删除）；
    - 对应节已非默认值（用户已在新路径配置过）→ 旧文件仅改名留档，不导入
      （UnifiedConfig 为唯一真相源，避免旧值反向覆盖）；
    - 旧文件解析/校验失败（非法字段 / 隐私红线越界）→ 跳过导入且**不**改名
      （保留现场供人工排查），告警留痕；
    - 幂等：迁移完成后旧文件已改名，二次启动不再触发任何动作。

    Args:
        legacy_dir: 旧配置目录（默认 server/autonomy/data/，测试可注入 tmp 目录）。

    Returns:
        {"autonomy": bool, "dream": bool}——各节是否发生了「导入」动作
        （仅改名留档返回 False，供调用方日志区分）。
    """

    def _is_default(section: BaseModel) -> bool:
        """判断配置节是否仍为全默认值（与空构造实例逐字段对比）。"""
        return section.model_dump() == type(section)().model_dump()

    results = {"autonomy": False, "dream": False}
    settings = get_settings()
    with _CONFIG_SAVE_LOCK:
        targets = (
            (
                "autonomy",
                AutonomySection,
                "autonomy_config.json",
            ),
            (
                "dream",
                DreamSection,
                "dream_config.json",
            ),
        )
        dir_path = Path(legacy_dir) if legacy_dir else _LEGACY_AUTONOMY_DATA_DIR
        imported_any = False
        for name, section_model, filename in targets:
            legacy_path = dir_path / filename
            if not legacy_path.exists():
                continue
            section = getattr(settings.config, name)
            try:
                raw = json.loads(legacy_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(
                    "AUTONOMY_CONFIG_MIGRATION: 旧配置 %s 读取失败，跳过迁移（保留现场）: %s",
                    legacy_path,
                    e,
                )
                continue
            try:
                imported = section_model.model_validate(raw)
            except Exception as e:  # noqa: BLE001 —— 非法旧档跳过迁移，保留现场
                logger.warning(
                    "AUTONOMY_CONFIG_MIGRATION: 旧配置 %s 字段非法，跳过迁移（保留现场）: %s",
                    legacy_path,
                    e,
                )
                continue
            if _is_default(section):
                # 节仍为全默认值 → 导入旧值
                setattr(settings.config, name, imported)
                results[name] = True
                imported_any = True
                logger.info(
                    "AUTONOMY_CONFIG_MIGRATION: %s 节已从 %s 导入 UnifiedConfig", name, legacy_path
                )
            else:
                logger.info(
                    "AUTONOMY_CONFIG_MIGRATION: %s 节已存在非默认配置，跳过导入（旧档仅留档）",
                    name,
                )
            # 留档：旧文件改名 <原名>.json.migrated（不删除；失败仅告警，不阻断）
            migrated_path = Path(str(legacy_path) + _MIGRATED_SUFFIX)
            try:
                os.replace(str(legacy_path), str(migrated_path))
            except OSError as e:
                logger.warning(
                    "AUTONOMY_CONFIG_MIGRATION: 旧配置 %s 改名留档失败: %s", legacy_path, e
                )
        if imported_any:
            save_config(settings.config)
    return results


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

    # 帧过滤器字段越界检查（spec add-vlm-frame-filter-face-match）
    if "filter_context_messages" in ve:
        v = ve["filter_context_messages"]
        if not isinstance(v, int) or v < 1 or v > 20:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.filter_context_messages={v} 越界（1-20），回退默认值 6")
            ve["filter_context_messages"] = 6
    if "filter_timeout_seconds" in ve:
        v = ve["filter_timeout_seconds"]
        if not isinstance(v, (int, float)) or v < 2 or v > 30:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.filter_timeout_seconds={v} 越界（2-30），回退默认值 8.0")
            ve["filter_timeout_seconds"] = 8.0
    if "filter_fail_mode" in ve:
        v = ve["filter_fail_mode"]
        if not isinstance(v, str) or v not in ("passthrough", "discard"):
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: vision_enhanced.filter_fail_mode={v!r} 非法（passthrough|discard），回退默认值 passthrough")
            ve["filter_fail_mode"] = "passthrough"

    # ---- face_match 节（人脸档案匹配）越界检查 ----
    fm = user_config.setdefault("face_match", {})
    if "provider" in fm:
        v = fm["provider"]
        if not isinstance(v, str) or v not in ("local", "external"):
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: face_match.provider={v!r} 非法（local|external），回退默认值 local")
            fm["provider"] = "local"
    if "sim_threshold" in fm:
        v = fm["sim_threshold"]
        if not isinstance(v, (int, float)) or v < 0.2 or v > 0.8:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: face_match.sim_threshold={v} 越界（0.2-0.8），回退默认值 0.45")
            fm["sim_threshold"] = 0.45
    if "max_faces_per_frame" in fm:
        v = fm["max_faces_per_frame"]
        if not isinstance(v, int) or v < 1 or v > 8:
            logger.warning(f"CONFIG_FIELD_OUT_OF_RANGE: face_match.max_faces_per_frame={v} 越界（1-8），回退默认值 4")
            fm["max_faces_per_frame"] = 4

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
