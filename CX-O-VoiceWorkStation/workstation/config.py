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
class SeparationConfig:
    """separation 段：翻唱分离引擎（demucs 人声/伴奏 + AudioSep 文本查询拆双人声部）。

    change-id: enhance-cover-pitch-analysis-duet（Task 1）。
    两引擎依赖不共存单环境，demucs_python_path 与 audiosep_python_path 分设，
    各自以子进程在引擎目录内执行（模式同 SoVitSSVCConfig.python_path）。
    """
    enabled: bool = True
    # 引擎目录：CX-O-VoiceWorkStation/engines/ 下（tools/setup_separation.py --clone 克隆）
    demucs_engine_dir: str = str(_BASE_DIR / "engines" / "demucs")
    audiosep_engine_dir: str = str(_BASE_DIR / "engines" / "AudioSep")
    # 两引擎依赖不共存单环境，分设子进程解释器（可为各自 venv 的 python）
    demucs_python_path: str = "python"
    audiosep_python_path: str = "python"
    # auto|cuda|cpu；auto 由引擎侧脚本探测 torch.cuda 可用性自判
    device: str = "auto"
    # demucs 模型名（人声/伴奏两轨分离 = htdemucs + --two-stems=vocals；
    # 注意 htdemucs_2s 非官方预训练名，2026-09-06 冒烟实测纠正）
    demucs_model: str = "htdemucs"
    # AudioSep checkpoint（.ckpt 绝对路径，如 audiosep_base_4M_steps.ckpt）；
    # 空 = 回退引擎内默认 checkpoint/ 目录探测（tools/setup_separation.py 校验）
    audiosep_checkpoint: str = ""
    # 分离产物根目录（每次分离落 data/separation/<uid>/）
    separation_dir: str = str(_BASE_DIR / "data" / "separation")
    # 单次分离子进程超时（秒），超时 terminate→kill
    subprocess_timeout_seconds: float = 600

    def __post_init__(self):
        # 数值钳制/空回退：device 越界回退 auto；超时钳制 [1, 3600]s；checkpoint 空白归一
        if self.device not in ("auto", "cuda", "cpu"):
            self.device = "auto"
        try:
            timeout = float(self.subprocess_timeout_seconds)
        except (TypeError, ValueError):
            timeout = 600.0
        self.subprocess_timeout_seconds = min(max(timeout, 1.0), 3600.0)
        self.audiosep_checkpoint = (self.audiosep_checkpoint or "").strip()


@dataclass
class CoverAnalysisConfig:
    """cover_analysis 段：源音频人声音域分析。

    change-id: enhance-cover-pitch-analysis-duet（Task 1）。
    training_data_dir 跨服务只读指向 ModelStation 训练数据
    （与 sovits_svc.models_dir 跨服务只读同模式，禁写入）。
    """
    # 训练数据根（raw/<speaker>/*.wav），用于目标模型音域画像（Task 2 消费，只读）
    training_data_dir: str = str(
        _BASE_DIR.parent / "CXO-ModelStation" / "data" / "training" / "sovits_svc"
    )
    # 画像缓存落盘目录（data/voice_profiles/<speaker>.json）
    voice_profiles_dir: str = str(_BASE_DIR / "data" / "voice_profiles")
    # pyin F0 置信度阈值（低于该值的帧不计入统计），钳制 [0, 1]
    f0_confidence: float = 0.6

    def __post_init__(self):
        try:
            confidence = float(self.f0_confidence)
        except (TypeError, ValueError):
            confidence = 0.6
        self.f0_confidence = min(max(confidence, 0.0), 1.0)


@dataclass
class WorkstationSettings:
    server: ServerConfig = field(default_factory=ServerConfig)
    sovits_svc: SoVitSSVCConfig = field(default_factory=SoVitSSVCConfig)
    audio_upload: AudioUploadConfig = field(default_factory=AudioUploadConfig)
    music: MusicConfig = field(default_factory=MusicConfig)
    cxfc: CXFCConfig = field(default_factory=CXFCConfig)
    separation: SeparationConfig = field(default_factory=SeparationConfig)
    cover_analysis: CoverAnalysisConfig = field(default_factory=CoverAnalysisConfig)


_settings: Optional[WorkstationSettings] = None


def get_settings() -> WorkstationSettings:
    global _settings
    if _settings is None:
        _settings = WorkstationSettings()
    return _settings
