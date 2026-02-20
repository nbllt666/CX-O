"""
配置管理模块
"""
import json
import os
from pathlib import Path
from typing import Any, Optional, List, Dict
from pydantic import BaseModel, Field


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


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8100
    cors: CorsConfig = Field(default_factory=CorsConfig)


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class AudioConfig(BaseModel):
    effects_dir: str = "data/effects"


class CosyVoiceConfig(BaseModel):
    url: str = "http://127.0.0.1:8003"
    timeout: int = 120
    enabled: bool = True
    auto_stop_delay: int = 300
    start_command: str = "python runtime/python/fastapi/server.py --port 8003 --model_dir pretrained_models/CosyVoice2-0.5B"
    working_dir: str = "CosyVoice"


class ServicesConfig(BaseModel):
    cxhms: ServiceConfig
    asr: ServiceConfig
    tts: TTSConfig
    audio: Optional[AudioConfig] = None
    cosyvoice: Optional[CosyVoiceConfig] = None


class Config(BaseModel):
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    services: ServicesConfig
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


_config: Optional[Config] = None


def get_config_path() -> Path:
    config_env = os.getenv("CXO_GATEWAY_CONFIG")
    if config_env:
        return Path(config_env)
    return Path(__file__).parent.parent / "config.json"


def load_config() -> Config:
    global _config
    if _config is not None:
        return _config
    
    config_path = get_config_path()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)
    
    _config = Config(**config_data)
    return _config


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
