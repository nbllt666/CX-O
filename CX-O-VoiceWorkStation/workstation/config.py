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
class SoVitSSVCConfig:
    enabled: bool = True
    output_dir: str = str(_BASE_DIR / "data" / "models" / "sovits_svc")
    training_data_dir: str = str(_BASE_DIR / "data" / "training" / "sovits_svc")
    so_vits_svc_dir: str = str(_BASE_DIR.parent / "so-vits-svc-4.1-Stable")
    python_path: str = "python"


@dataclass
class VoxCPMConfig:
    model_path: str = "openbmb/VoxCPM2"
    device: str = "auto"
    enable_denoiser: bool = True
    cfg_value: float = 2.0
    inference_timesteps: int = 10
    zipenhancer_model_path: str = "iic/speech_zipenhancer_ans_multiloss_16k_base"
    working_dir: str = "VoxCPM-main"


@dataclass
class OrpheusConfig:
    """Orpheus TTS 配置（直调 docker vLLM 服务，OpenAI 兼容 API）。"""
    url: str = "http://127.0.0.1:5060"
    voice: str = "tara"
    timeout: int = 60


@dataclass
class F5TTSConfig:
    """F5-TTS 配置（通过 HTTP 调用 CX-O-SERVER 的 f5tts 合成能力，VoiceWorkStation 不自载模型）。

    ref_audio_path / ref_text 为 SVC 训练数据生成（engine=f5tts）的默认参考音频与文本；
    通常由批量数据集请求显式传入，配置项作为兜底默认值。
    """
    server_url: str = "http://127.0.0.1:8000"
    timeout: int = 300
    ref_audio_path: str = ""
    ref_text: str = ""


@dataclass
class OutputConfig:
    voice_refs_dir: str = str(_BASE_DIR.parent / "CX-O-SERVER" / "data" / "voice_refs")


@dataclass
class MusicConfig:
    songs_dir: str = str(_BASE_DIR / "data" / "songs")
    soundfont_path: str = ""
    # 默认接入真实 DiffSinger 引擎（spec「真实 DiffSinger 引擎接入」要求）；
    # MockSingingEngine 保留为开发/CI 选项，显式配置 singing_engine="mock" 即可切回。
    singing_engine: str = "diffsinger"
    diffsinger_dir: str = str(_BASE_DIR.parent / "DiffSinger")
    # DiffSinger 依赖 torch/numpy<2/librosa/lightning 等，仅在 cx-o conda 环境中安装；
    # 系统 Python 3.14 缺少这些依赖，必须指向 cx-o 环境解释器。
    diffsinger_python: str = r"C:\Users\NBLLT666\.conda\envs\cx-o\python.exe"
    # 默认声库：OpenCpop DS1000 声学模型（已部署于 checkpoints/0211_opencpop_ds1000_keyshift/）
    voice_bank: str = "0211_opencpop_ds1000_keyshift"
    default_svc_model: str = ""


@dataclass
class CXFCConfig:
    enabled: bool = True
    server_url: str = "http://127.0.0.1:8000"
    auto_register: bool = True
    heartbeat_interval: int = 15
    plugin_name: str = "voiceworkstation-music"


@dataclass
class WorkstationSettings:
    server: ServerConfig = field(default_factory=ServerConfig)
    sovits_svc: SoVitSSVCConfig = field(default_factory=SoVitSSVCConfig)
    voxcpm: VoxCPMConfig = field(default_factory=VoxCPMConfig)
    orpheus: OrpheusConfig = field(default_factory=OrpheusConfig)
    f5tts: F5TTSConfig = field(default_factory=F5TTSConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    music: MusicConfig = field(default_factory=MusicConfig)
    cxfc: CXFCConfig = field(default_factory=CXFCConfig)


_settings: Optional[WorkstationSettings] = None


def get_settings() -> WorkstationSettings:
    global _settings
    if _settings is None:
        _settings = WorkstationSettings()
    return _settings
