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
    # 默认仅绑定本机回环：服务含训练/文件操作接口，默认不暴露到局域网；
    # 局域网部署可显式改配置（如 CXO_VWS_HOST 环境变量或配置文件）。
    host: str = "127.0.0.1"
    port: int = 8200
    log_level: str = "INFO"
    debug: bool = True
    # CORS 白名单：前端管理界面来源 + file:// 源（null）。
    # 可经环境变量 CXO_VWS_CORS_ORIGINS（逗号分隔）覆盖；默认不再放开 "*"。
    cors_origins: list = field(default_factory=lambda: [
        origin.strip()
        for origin in os.environ.get(
            "CXO_VWS_CORS_ORIGINS",
            "http://localhost:3100,http://127.0.0.1:3100,null",
        ).split(",")
        if origin.strip()
    ])


@dataclass
class SoVitSSVCConfig:
    # 瘦身后仅保留推理与模型列表能力；训练全链路已迁至 CXO-ModelStation（8300）。
    enabled: bool = True
    # 模型目录：指向 ModelStation 的模型产出（只读消费：列表 + 推理输入）。
    # 以 _BASE_DIR.parent 锚定项目根解析（与 so_vits_svc_dir 同先例），禁 CWD 相对。
    models_dir: str = str(_BASE_DIR.parent / "CXO-ModelStation" / "data" / "models" / "sovits_svc")
    # 推理结果输出目录：VWS 自有受控目录（audio-files svc-results 类别映射此目录）
    infer_output_dir: str = str(_BASE_DIR / "data" / "svc-results")
    # 引擎目录：2026-09-05 so-vits-svc-4.1-Stable 迁入 CXO-ModelStation/engines/
    # （自包含化，单一真源，与 ModelStation config 默认值一致），VWS 只读推理共用。
    so_vits_svc_dir: str = str(_BASE_DIR.parent / "CXO-ModelStation" / "engines" / "so-vits-svc-4.1-Stable")
    python_path: str = "python"


@dataclass
class AudioUploadConfig:
    # 受控上传（POST /api/audio-uploads）：翻唱音频入口，落盘目录为
    # SoVITSSVCInferer allowed_audio_root 白名单根（data/input/），上传即可推理。
    max_size_mb: int = 50
    input_dir: str = str(_BASE_DIR / "data" / "input")


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
    plugin_name: str = "作曲翻唱CXFC"


@dataclass
class WorkstationSettings:
    server: ServerConfig = field(default_factory=ServerConfig)
    sovits_svc: SoVitSSVCConfig = field(default_factory=SoVitSSVCConfig)
    audio_upload: AudioUploadConfig = field(default_factory=AudioUploadConfig)
    music: MusicConfig = field(default_factory=MusicConfig)
    cxfc: CXFCConfig = field(default_factory=CXFCConfig)


_settings: Optional[WorkstationSettings] = None


def get_settings() -> WorkstationSettings:
    global _settings
    if _settings is None:
        _settings = WorkstationSettings()
    return _settings
