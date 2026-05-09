"""
CX-O-VoiceWorkStation 配置模块
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

_BASE_DIR = Path(__file__).parent.parent


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8200
    log_level: str = "INFO"
    debug: bool = True


@dataclass
class CosyVoiceConfig:
    url: str = "http://127.0.0.1:50000"
    model: str = "CosyVoice2-0.5B"
    default_mode: str = "instruct2"
    timeout: float = 120.0
    default_spk_id: str = "中文女"


@dataclass
class IndexTTSConfig:
    url: str = "http://127.0.0.1:8004"
    enabled: bool = True
    timeout: float = 180.0
    start_command: str = ""
    working_dir: str = "IndexTTS"
    auto_stop_delay: int = 300
    startup_timeout: int = 180


@dataclass
class F5TTSFinetuneConfig:
    enabled: bool = True
    base_model: str = "F5TTS_v1_Base"
    output_dir: str = str(_BASE_DIR / "data" / "models" / "f5tts")
    training_data_dir: str = str(_BASE_DIR / "data" / "training" / "f5tts")


@dataclass
class SoVitSSVCConfig:
    enabled: bool = True
    output_dir: str = str(_BASE_DIR / "data" / "models" / "sovits_svc")
    training_data_dir: str = str(_BASE_DIR / "data" / "training" / "sovits_svc")


@dataclass
class OutputConfig:
    voice_refs_dir: str = str(_BASE_DIR.parent / "CX-O-SERVER" / "data" / "voice_refs")


@dataclass
class WorkstationSettings:
    server: ServerConfig = field(default_factory=ServerConfig)
    cosyvoice: CosyVoiceConfig = field(default_factory=CosyVoiceConfig)
    index_tts: IndexTTSConfig = field(default_factory=IndexTTSConfig)
    f5tts_finetune: F5TTSFinetuneConfig = field(default_factory=F5TTSFinetuneConfig)
    sovits_svc: SoVitSSVCConfig = field(default_factory=SoVitSSVCConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


_settings: Optional[WorkstationSettings] = None


def get_settings() -> WorkstationSettings:
    global _settings
    if _settings is None:
        _settings = WorkstationSettings()
    return _settings
