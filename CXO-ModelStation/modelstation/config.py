"""CXO-ModelStation 服务配置。

字段语义（auto_fill，参照 CXO-Tuner config 模式）：
  - 缺失字段按各属性 default 自动补齐；
  - 越界值（越出取值范围）回退到对应默认值；
  - 支持环境变量 CXO_MODELSTATION_CONFIG（JSON 字符串）覆盖默认值。

所有未显式配置的目录默认值基于本文件 __file__ 解析：
  - modelstation/config.py 的 parents[1] = CXO-ModelStation（数据目录与引擎目录锚点）；
  - 引擎目录（so-vits-svc-4.1-Stable / VoxCPM-main / MeloTTS）自 2026-09-05 起迁入
    CXO-ModelStation/engines/（自包含部署，无 ../ 项目根依赖）。
禁止 CWD 相对解析（rules-0 §三）。
"""
from __future__ import annotations

import json
import os
import logging
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# 基于 __file__ 解析锚点（禁 CWD 相对路径）
_PKG_DIR = Path(__file__).resolve().parent            # .../CXO-ModelStation/modelstation
_BASE_DIR = _PKG_DIR.parent                            # .../CXO-ModelStation
_PROJECT_ROOT = _BASE_DIR.parent                       # .../CX-O（项目根，仅注释/调试用途保留）

DEFAULT_TRAINING_DATA_DIR = str(_BASE_DIR / "data" / "training" / "sovits_svc")
DEFAULT_MODELS_DIR = str(_BASE_DIR / "data" / "models" / "sovits_svc")
DEFAULT_AUDITION_DIR = str(_BASE_DIR / "data" / "audition")
DEFAULT_INPUT_DIR = str(_BASE_DIR / "data" / "input")
# 引擎目录锚定 CXO-ModelStation/engines/（自包含部署：整体拷贝目录即可运行）
DEFAULT_SO_VITS_SVC_DIR = str(_BASE_DIR / "engines" / "so-vits-svc-4.1-Stable")
DEFAULT_VOXCPM_WORKING_DIR = str(_BASE_DIR / "engines" / "VoxCPM-main")
DEFAULT_MELOTTS_ENGINE_DIR = str(_BASE_DIR / "engines" / "MeloTTS")

_DEFAULT_PORT = 8300
_VALID_LOG_LEVELS = ("critical", "error", "warning", "info", "debug", "trace")
_DEFAULT_LOG_LEVEL = "info"
_DEFAULT_CORS_ORIGINS = [
    "http://localhost:3300",
    "http://127.0.0.1:3300",
    "http://localhost:3100",
]


class ServerConfig(BaseModel):
    """server 段：host/port/log_level/cors_origins。

    - 默认仅绑定本机回环：服务含训练/文件操作接口，默认不暴露到局域网；
    - port 越界（非 1-65535 或不可解析）回退 8300；
    - log_level 不在合法枚举内回退 info；
    - cors_origins 可经字符串（逗号分隔）提供。
    """

    host: str = "127.0.0.1"
    port: int = _DEFAULT_PORT
    log_level: str = _DEFAULT_LOG_LEVEL
    cors_origins: list = Field(default_factory=lambda: list(_DEFAULT_CORS_ORIGINS))

    @field_validator("host")
    @classmethod
    def _fill_host(cls, v: Any) -> str:
        s = "" if v is None else str(v).strip()
        return s or "127.0.0.1"

    @field_validator("port", mode="before")
    @classmethod
    def _clamp_port(cls, v: Any) -> int:
        try:
            num = int(v)
        except (TypeError, ValueError):
            return _DEFAULT_PORT
        return num if 1 <= num <= 65535 else _DEFAULT_PORT

    @field_validator("log_level", mode="before")
    @classmethod
    def _fill_log_level(cls, v: Any) -> str:
        s = ("" if v is None else str(v)).strip().lower()
        return s if s in _VALID_LOG_LEVELS else _DEFAULT_LOG_LEVEL

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _fill_cors_origins(cls, v: Any) -> list:
        if v is None:
            return list(_DEFAULT_CORS_ORIGINS)
        if isinstance(v, str):
            items = [origin.strip() for origin in v.split(",") if origin.strip()]
            return items
        if isinstance(v, (list, tuple)):
            return [str(origin).strip() for origin in v if str(origin).strip()]
        return list(_DEFAULT_CORS_ORIGINS)


class SoVitSSVCConfig(BaseModel):
    """sovits_svc 段：训练/模型/试听/输入目录与上游引擎路径。

    目录默认值全部锚定 CXO-ModelStation（_BASE_DIR，含 engines/ 引擎目录），
    与 CWD 无关。
    """

    training_data_dir: str = DEFAULT_TRAINING_DATA_DIR
    models_dir: str = DEFAULT_MODELS_DIR
    # 试听推理输出目录（infer 产物落盘，经 /api/audio-files/audition 提供）
    audition_dir: str = DEFAULT_AUDITION_DIR
    # 推理输入白名单根之一（与训练数据目录并列，spec「infer 输入白名单根 = 训练数据目录 ∪ data/input」）
    input_dir: str = DEFAULT_INPUT_DIR
    so_vits_svc_dir: str = DEFAULT_SO_VITS_SVC_DIR
    python_path: str = "python"

    @field_validator("training_data_dir", "models_dir", "audition_dir", "input_dir", "so_vits_svc_dir")
    @classmethod
    def _fill_dirs(cls, v: Any, info) -> str:
        s = "" if v is None else str(v).strip()
        if s:
            return s
        defaults = {
            "training_data_dir": DEFAULT_TRAINING_DATA_DIR,
            "models_dir": DEFAULT_MODELS_DIR,
            "audition_dir": DEFAULT_AUDITION_DIR,
            "input_dir": DEFAULT_INPUT_DIR,
            "so_vits_svc_dir": DEFAULT_SO_VITS_SVC_DIR,
        }
        return defaults[info.field_name]

    @field_validator("python_path", mode="before")
    @classmethod
    def _fill_python_path(cls, v: Any) -> str:
        s = "" if v is None else str(v).strip()
        return s or "python"


class VoxCPMConfig(BaseModel):
    """voxcpm 段：批量语料生成引擎配置。

    model_path/working_dir 为 spec 冻结字段；device/enable_denoiser/cfg_value/
    inference_timesteps/zipenhancer_model_path 为引擎 CLI 参数（随迁移代码带入，
    缺省值与原 VWS 一致，保证子进程调用行为不变）。
    """

    model_path: str = "openbmb/VoxCPM2"
    working_dir: str = DEFAULT_VOXCPM_WORKING_DIR
    device: str = "auto"
    enable_denoiser: bool = True
    cfg_value: float = 2.0
    inference_timesteps: int = 10
    zipenhancer_model_path: str = "iic/speech_zipenhancer_ans_multiloss_16k_base"

    @field_validator("model_path")
    @classmethod
    def _fill_model_path(cls, v: Any) -> str:
        s = "" if v is None else str(v).strip()
        return s or "openbmb/VoxCPM2"

    @field_validator("working_dir")
    @classmethod
    def _fill_working_dir(cls, v: Any) -> str:
        s = "" if v is None else str(v).strip()
        return s or DEFAULT_VOXCPM_WORKING_DIR


class MeloTTSConfig(BaseModel):
    """melotts 段：MeloTTS 微调训练引擎配置。

    - engine_dir 锚定 CXO-ModelStation/engines/MeloTTS（setup 脚本克隆就位）；
    - training_data_dir/models_dir 为训练数据与模型产物目录；
    - base_checkpoint 为空时由 MeloTTS 管线使用官方默认预训练模型下载。
    """

    engine_dir: str = DEFAULT_MELOTTS_ENGINE_DIR
    training_data_dir: str = str(_BASE_DIR / "data" / "training" / "melotts")
    models_dir: str = str(_BASE_DIR / "data" / "models" / "melotts")
    python_path: str = "python"
    language: str = "ZH"
    # 预训练基础模型路径，空=用 MeloTTS 官方默认下载
    base_checkpoint: str = ""

    @field_validator("engine_dir", "training_data_dir", "models_dir", mode="before")
    @classmethod
    def _fill_dirs(cls, v: Any, info) -> str:
        s = "" if v is None else str(v).strip()
        if s:
            return s
        defaults = {
            "engine_dir": DEFAULT_MELOTTS_ENGINE_DIR,
            "training_data_dir": str(_BASE_DIR / "data" / "training" / "melotts"),
            "models_dir": str(_BASE_DIR / "data" / "models" / "melotts"),
        }
        return defaults[info.field_name]

    @field_validator("python_path", mode="before")
    @classmethod
    def _fill_python_path(cls, v: Any) -> str:
        s = "" if v is None else str(v).strip()
        return s or "python"

    @field_validator("language", mode="before")
    @classmethod
    def _fill_language(cls, v: Any) -> str:
        s = ("" if v is None else str(v)).strip().upper()
        return s or "ZH"


class TTSTuntimeConfig(BaseModel):
    """tts_runtime 段：数据集生成用的 vLLM 合成运行时端点（OpenAI 兼容）。

    同机部署默认回环端口；跨机部署经 CXO_MODELSTATION_CONFIG 指向远端。
    timeout_seconds/sample_rate 越界或不可解析时回退默认值。
    """

    voicedesign_base_url: str = "http://127.0.0.1:8091"
    voicedesign_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    cosyvoice_base_url: str = "http://127.0.0.1:8094"
    cosyvoice_model: str = "Fun-CosyVoice3-0.5B-2512"
    timeout_seconds: float = 120
    sample_rate: int = 24000

    @field_validator("voicedesign_base_url", "cosyvoice_base_url")
    @classmethod
    def _fill_base_url(cls, v: Any, info) -> str:
        s = "" if v is None else str(v).strip().rstrip("/")
        if s:
            return s
        defaults = {
            "voicedesign_base_url": "http://127.0.0.1:8091",
            "cosyvoice_base_url": "http://127.0.0.1:8094",
        }
        return defaults[info.field_name]

    @field_validator("voicedesign_model", "cosyvoice_model")
    @classmethod
    def _fill_model(cls, v: Any, info) -> str:
        s = "" if v is None else str(v).strip()
        if s:
            return s
        defaults = {
            "voicedesign_model": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
            "cosyvoice_model": "Fun-CosyVoice3-0.5B-2512",
        }
        return defaults[info.field_name]

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def _clamp_timeout(cls, v: Any) -> float:
        try:
            num = float(v)
        except (TypeError, ValueError):
            return 120.0
        # 越界（非正或超上限 3600s）回退默认
        return num if 0 < num <= 3600 else 120.0

    @field_validator("sample_rate", mode="before")
    @classmethod
    def _clamp_sample_rate(cls, v: Any) -> int:
        try:
            num = int(v)
        except (TypeError, ValueError):
            return 24000
        # 合法音频采样率范围 8kHz-192kHz，越界回退默认
        return num if 8000 <= num <= 192000 else 24000


class ModelStationSettings(BaseModel):
    """CXO-ModelStation 顶层配置（server / sovits_svc / voxcpm / melotts / tts_runtime）。"""

    server: ServerConfig = Field(default_factory=ServerConfig)
    sovits_svc: SoVitSSVCConfig = Field(default_factory=SoVitSSVCConfig)
    voxcpm: VoxCPMConfig = Field(default_factory=VoxCPMConfig)
    melotts: MeloTTSConfig = Field(default_factory=MeloTTSConfig)
    tts_runtime: TTSTuntimeConfig = Field(default_factory=TTSTuntimeConfig)


_settings: Optional[ModelStationSettings] = None


def load_config(raw: Optional[dict] = None) -> ModelStationSettings:
    """加载配置并完成 auto_fill。

    raw 为 None 时尝试从环境变量 CXO_MODELSTATION_CONFIG 读取 JSON（解析失败按空配置处理），
    否则使用 raw / 空配置。返回值已完整补齐默认值、越界回退。
    """
    data: dict = {}
    if raw is None:
        env = os.environ.get("CXO_MODELSTATION_CONFIG")
        if env:
            try:
                loaded = json.loads(env)
                if isinstance(loaded, dict):
                    data = loaded
            except json.JSONDecodeError as e:
                logger.warning("CXO_MODELSTATION_CONFIG JSON 解析失败，按空配置处理: %s", e)
    else:
        data = raw
    return ModelStationSettings.model_validate(data)


def get_settings() -> ModelStationSettings:
    """获取进程级配置单例（API 层消费入口）。"""
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings


def reset_settings() -> None:
    """重置配置单例（测试专用）。"""
    global _settings
    _settings = None
