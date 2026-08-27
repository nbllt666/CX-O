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
class MusicConfig:
    songs_dir: str = str(_BASE_DIR / "data" / "songs")
    soundfont_path: str = ""
    # 默认接入真实 DiffSinger 引擎（spec「真实 DiffSinger 引擎接入」要求）；
    # MockSingingEngine 保留为开发/CI 选项，显式配置 singing_engine="mock" 即可切回。
    singing_engine: str = "diffsinger"
    diffsinger_dir: str = str(_BASE_DIR.parent / "DiffSinger")
    # DiffSinger 依赖 torch/numpy<2/librosa/lightning 等，需在 cx-o conda 环境中安装；
    # 系统 Python 缺少这些依赖。批E-8：默认不再硬编码作者本机路径（换机即失效），
    # 改为空串 + CXO_DIFFSINGER_PYTHON 环境变量覆盖。空串时由消费方
    #（services/singing_engine、tools/setup_singing_engine）给出可读的「未配置」错误。
    diffsinger_python: str = os.environ.get("CXO_DIFFSINGER_PYTHON", "")
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
    music: MusicConfig = field(default_factory=MusicConfig)
    cxfc: CXFCConfig = field(default_factory=CXFCConfig)


_settings: Optional[WorkstationSettings] = None


def get_settings() -> WorkstationSettings:
    global _settings
    if _settings is None:
        _settings = WorkstationSettings()
    return _settings
