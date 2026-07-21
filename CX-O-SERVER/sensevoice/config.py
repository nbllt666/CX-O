import os
from typing import Optional
from pydantic import BaseModel
from enum import Enum


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Settings(BaseModel):
    device: str = os.getenv("SENSEVOICE_DEVICE", "cuda:0")
    host: str = os.getenv("SENSEVOICE_HOST", "0.0.0.0")
    port: int = int(os.getenv("SENSEVOICE_PORT", "8005"))
    workers: int = int(os.getenv("SENSEVOICE_WORKERS", "1"))
    log_level: LogLevel = LogLevel.INFO
    max_concurrent_requests: int = int(os.getenv("SENSEVOICE_MAX_CONCURRENT", "10"))
    request_timeout: int = int(os.getenv("SENSEVOICE_TIMEOUT", "300"))
    model_dir: str = os.getenv("SENSEVOICE_MODEL_DIR", "iic/SenseVoiceSmall")
    audio_sample_rate: int = 16000
    max_audio_length: int = 300
    enable_cors: bool = os.getenv("SENSEVOICE_ENABLE_CORS", "true").lower() == "true"
    # WebSocket streaming 配置（方案B：SenseVoice 加 WS 接口）
    # partial_threshold_ms：累积到此时长（毫秒）触发一次 partial 识别
    # 200ms 是平衡点：短则延迟低但识别准确率低，长则延迟高但准确率高
    # 16kHz mono int16 PCM：200ms = 3200 samples × 2 bytes = 6400 bytes
    partial_threshold_ms: int = int(os.getenv("SENSEVOICE_PARTIAL_THRESHOLD_MS", "200"))


settings = Settings()


class ASRConfig(BaseModel):
    language: str = "auto"
    use_itn: bool = True
    merge_vad: bool = True
    merge_length_s: int = 15
    ban_emo_unk: bool = False


DEFAULT_ASR_CONFIG = ASRConfig()
