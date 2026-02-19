"""
配置管理模块
"""
import json
import os
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel, Field


class ServiceConfig(BaseModel):
    url: str
    timeout: int = 30
    pool_size: int = 5
    reconnect_interval: int = 5
    heartbeat_interval: int = 30


class GatewayConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8100


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class ServicesConfig(BaseModel):
    cxhms: ServiceConfig
    asr: ServiceConfig
    tts: ServiceConfig


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
