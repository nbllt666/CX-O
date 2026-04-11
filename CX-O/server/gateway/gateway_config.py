"""
配置管理模块
支持环境变量 + JSON 配置文件混合配置
环境变量优先级高于配置文件
"""
import json
import os
from pathlib import Path
from typing import Any, Optional, List, Dict
from pydantic import BaseModel, ConfigDict, Field


ENV_PREFIX = "CXO_GATEWAY_"


def get_env_config() -> Dict[str, Any]:
    env_config: Dict[str, Any] = {"services": {}, "gateway": {}, "logging": {}}

    if os.getenv(f"{ENV_PREFIX}HOST"):
        env_config["gateway"]["host"] = os.getenv(f"{ENV_PREFIX}HOST")
    if os.getenv(f"{ENV_PREFIX}PORT"):
        env_config["gateway"]["port"] = int(os.getenv(f"{ENV_PREFIX}PORT"))

    if os.getenv(f"{ENV_PREFIX}CXHMS_URL"):
        env_config["services"]["cxhms"] = env_config["services"].get("cxhms", {})
        env_config["services"]["cxhms"]["url"] = os.getenv(f"{ENV_PREFIX}CXHMS_URL")
    if os.getenv(f"{ENV_PREFIX}CXHMS_HTTP_URL"):
        env_config["services"]["cxhms"] = env_config["services"].get("cxhms", {})
        env_config["services"]["cxhms"]["http_url"] = os.getenv(f"{ENV_PREFIX}CXHMS_HTTP_URL")

    if os.getenv(f"{ENV_PREFIX}ASR_URL"):
        env_config["services"]["asr"] = env_config["services"].get("asr", {})
        env_config["services"]["asr"]["url"] = os.getenv(f"{ENV_PREFIX}ASR_URL")

    if os.getenv(f"{ENV_PREFIX}TTS_URL"):
        env_config["services"]["tts"] = env_config["services"].get("tts", {})
        env_config["services"]["tts"]["url"] = os.getenv(f"{ENV_PREFIX}TTS_URL")

    if os.getenv(f"{ENV_PREFIX}INDEX_TTS_URL"):
        env_config["services"]["index_tts"] = env_config["services"].get("index_tts", {})
        env_config["services"]["index_tts"]["url"] = os.getenv(f"{ENV_PREFIX}INDEX_TTS_URL")

    if os.getenv(f"{ENV_PREFIX}LOG_LEVEL"):
        env_config["logging"]["level"] = os.getenv(f"{ENV_PREFIX}LOG_LEVEL")

    env_config = {k: v for k, v in env_config.items() if v}
    env_config["services"] = {k: v for k, v in env_config.get("services", {}).items() if v}

    return env_config


class BaseModel(BaseModel):
    pass


class CorsConfig(BaseModel):
    allow_origins: List[str] = Field(default_factory=lambda: ["*"])
    allow_methods: List[str] = Field(default_factory=lambda: ["*"])
    allow_headers: List[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = True


class ServiceConfig(BaseModel):
    url: str
    http_url: Optional[str] = None
    timeout: int = 30
    pool_size: int = 5
    reconnect_interval: int = 5
    heartbeat_interval: int = 30


class EmotionVoiceConfig(BaseModel):
    ref_audio: str = ""
    ref_text: str = ""


class TTSConfig(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    url: str
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


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8100
    cors: CorsConfig = Field(default_factory=CorsConfig)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


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
    cxhms: ServiceConfig
    asr: ServiceConfig
    tts: TTSConfig
    audio: Optional[AudioConfig] = None
    index_tts: Optional[IndexTTSConfig] = None
    control_service_url: Optional[str] = None
    adaptive_polling: Optional[AdaptivePollingConfig] = None
    sensevoice_streaming: Optional[SenseVoiceStreamingConfig] = None


class Config(BaseModel):
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    services: ServicesConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


_config: Optional[Config] = None


def get_config_path() -> Path:
    config_env = os.getenv("CXO_GATEWAY_CONFIG")
    if config_env:
        return Path(config_env)
    return Path(__file__).parent.parent.parent / "config.json"


def load_config() -> Config:
    global _config
    if _config is not None:
        return _config

    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    env_config = get_env_config()
    config_data = deep_merge(config_data, env_config)

    _config = Config(**config_data)
    return _config


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_config() -> Config:
    if _config is None:
        return load_config()
    return _config


def save_config(config: Config) -> None:
    global _config
    config_path = get_config_path()

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=4, ensure_ascii=False)

    _config = config


def get_service_url(service_name: str) -> str:
    config = get_config()
    service_config = getattr(config.services, service_name, None)
    if service_config is None:
        raise ValueError(f"Unknown service: {service_name}")
    return service_config.url


def reload_config() -> Config:
    global _config
    _config = None
    return load_config()