"""
CX-O-SERVER 统一配置模块
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config.settings import settings as _shared_settings


class ASRConfig:
    mode: str = "remote"
    model_dir: str = "SenseVoiceSmall"
    device: str = "cuda"
    remote_url: str = "http://127.0.0.1:8001"

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TTSConfig:
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

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class VoiceWorkstationConfig:
    url: str = "http://127.0.0.1:8200"
    enabled: bool = True

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class ServerSettings:
    def __init__(self):
        self._shared = _shared_settings
        self.system = getattr(self._shared.config, 'system', type('obj', (), {'host': '0.0.0.0', 'port': 8100, 'log_level': 'INFO', 'debug': True})())
        self.cors = getattr(self._shared.config, 'cors', None)

        asr_cfg = getattr(self._shared.config, 'asr', None) or {}
        if isinstance(asr_cfg, dict):
            self.asr = ASRConfig(**asr_cfg)
        else:
            self.asr = ASRConfig(
                mode=getattr(asr_cfg, 'mode', 'remote'),
                model_dir=getattr(asr_cfg, 'model_dir', 'SenseVoiceSmall'),
                device=getattr(asr_cfg, 'device', 'cuda'),
                remote_url=getattr(asr_cfg, 'remote_url', 'http://127.0.0.1:8001'),
            )

        tts_raw = getattr(self._shared.config, 'tts', None)
        if isinstance(tts_raw, dict):
            self.tts = TTSConfig(**tts_raw)
        else:
            self.tts = TTSConfig(
                mode=getattr(tts_raw, 'mode', 'remote') if tts_raw else 'remote',
                model_dir=getattr(tts_raw, 'model_dir', 'F5TTS_v1_Base') if tts_raw else 'F5TTS_v1_Base',
                device=getattr(tts_raw, 'device', 'cuda') if tts_raw else 'cuda',
                remote_url=getattr(tts_raw, 'url', 'http://127.0.0.1:5000') if tts_raw else 'http://127.0.0.1:5000',
                ref_audio_path=getattr(tts_raw, 'ref_audio_path', '') if tts_raw else '',
                ref_text=getattr(tts_raw, 'ref_text', '') if tts_raw else '',
                speed=getattr(tts_raw, 'speed', 1.0) if tts_raw else 1.0,
                cross_fade_duration=getattr(tts_raw, 'cross_fade_duration', 0.15) if tts_raw else 0.15,
                emotion_enabled=getattr(tts_raw, 'emotion_enabled', True) if tts_raw else True,
                effects_enabled=getattr(tts_raw, 'effects_enabled', True) if tts_raw else True,
            )

        vw_cfg = getattr(self._shared.config, 'voice_workstation', None) or {}
        if isinstance(vw_cfg, dict):
            self.voice_workstation = VoiceWorkstationConfig(**vw_cfg)
        else:
            self.voice_workstation = VoiceWorkstationConfig(
                url=getattr(vw_cfg, 'url', 'http://127.0.0.1:8200'),
                enabled=getattr(vw_cfg, 'enabled', True),
            )

        self.config = self._shared.config


_settings: Optional[ServerSettings] = None


def get_settings() -> ServerSettings:
    global _settings
    if _settings is None:
        _settings = ServerSettings()
    return _settings
