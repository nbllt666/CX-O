"""CXO-Tuner 服务配置。

字段对齐 public/schema/cxo_tuner_config.schema.json。
语义：
  - 缺失字段按各属性 default 自动补齐（auto_fill）；
  - 越界值（越出取值范围）回退到对应默认值。
所有未显式配置的输出目录基于本文件 __file__ 解析到 CXO-Tuner/data 下。
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

# 基于 __file__ 解析 CXO-Tuner 根目录下的默认数据目录
_TUNER_PKG_DIR = os.path.dirname(os.path.abspath(__file__))  # .../CXO-Tuner/tuner
_PROJECT_ROOT = os.path.dirname(_TUNER_PKG_DIR)  # .../CXO-Tuner
DEFAULT_DATASET_DIR = os.path.join(_PROJECT_ROOT, "data", "dataset")
DEFAULT_LORA_DIR = os.path.join(_PROJECT_ROOT, "data", "lora")
DEFAULT_ANCHOR_DIR = os.path.join(_PROJECT_ROOT, "data", "anchors")

_GENERAL_DEFAULTS: Dict[str, float] = {
    "anchor_ratio": 0.2,
    "max_memory_fraction": 0.8,
    "max_lr": 0.000001,
    "min_dataset_size": 100,
}

_CUDA_PATTERN = re.compile(r"^[0-9]*(?:,[0-9]+)*$")
_TIME_PATTERN = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


def _fallback_number(value: Any, low: float, high: float, default: float) -> float:
    """越界（或不可解析）时回退到给定默认值。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return num if low <= num <= high else default


class TrainerConfig(BaseModel):
    """对齐 cxo_tuner_config.schema.json 的 trainer 段。"""

    CUDA_VISIBLE_DEVICES: str = ""
    max_memory_fraction: float = 0.8

    @field_validator("CUDA_VISIBLE_DEVICES")
    @classmethod
    def _cuda_devices(cls, v: Any) -> str:
        s = "" if v is None else str(v)
        return s if _CUDA_PATTERN.fullmatch(s) else ""

    @field_validator("max_memory_fraction")
    @classmethod
    def _clamp_memory(cls, v: Any) -> float:
        return _fallback_number(v, 0.0, 1.0, _GENERAL_DEFAULTS["max_memory_fraction"])


class SchedulerConfig(BaseModel):
    """对齐 cxo_tuner_config.schema.json 的 scheduler 段。"""

    enabled: bool = True
    idle_start: str = "02:00"
    idle_end: str = "05:00"
    min_dataset_size: int = 100

    @field_validator("idle_start", "idle_end")
    @classmethod
    def _idle_time(cls, v: Any, info) -> str:
        s = "" if v is None else str(v)
        if not _TIME_PATTERN.fullmatch(s):
            return "02:00" if info.field_name == "idle_start" else "05:00"
        return s

    @field_validator("min_dataset_size")
    @classmethod
    def _clamp_min_size(cls, v: Any) -> int:
        try:
            n = int(v)
        except (TypeError, ValueError):
            return _GENERAL_DEFAULTS["min_dataset_size"]
        return n if n >= 1 else _GENERAL_DEFAULTS["min_dataset_size"]


class OnlineDpoConfig(BaseModel):
    """对齐 cxo_tuner_config.schema.json 的 online_dpo 段。"""

    enabled: bool = False
    max_lr: float = 0.000001

    @field_validator("max_lr")
    @classmethod
    def _clamp_lr(cls, v: Any) -> float:
        return _fallback_number(v, 0.0, float("inf"), _GENERAL_DEFAULTS["max_lr"])


class TunerConfig(BaseModel):
    """CXO-Tuner 服务自身配置。

    - judge_model / base_model / vllm_url：必填，用户在 config 中提供。
    - dataset_dir / lora_dir：默认指向 CXO-Tuner/data 下（__file__ 解析），可覆盖。
    - 其余数值/布尔字段缺失自动补默认，越界回退默认。
    """

    judge_model: str = ""
    base_model: str = ""
    anchor_ratio: float = 0.2
    trainer: TrainerConfig = Field(default_factory=TrainerConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    online_dpo: OnlineDpoConfig = Field(default_factory=OnlineDpoConfig)
    dataset_dir: str = DEFAULT_DATASET_DIR
    lora_dir: str = DEFAULT_LORA_DIR
    character_cards_dir: str = DEFAULT_ANCHOR_DIR
    vllm_url: str = ""
    vllm_lora_enabled: bool = False

    @field_validator("anchor_ratio")
    @classmethod
    def _clamp_anchor_ratio(cls, v: Any) -> float:
        return _fallback_number(v, 0.0, 1.0, _GENERAL_DEFAULTS["anchor_ratio"])

    @field_validator("dataset_dir", "lora_dir", "character_cards_dir")
    @classmethod
    def _resolve_dirs(cls, v: Any, info) -> str:
        if v is None or not str(v).strip():
            if info.field_name == "lora_dir":
                return DEFAULT_LORA_DIR
            if info.field_name == "character_cards_dir":
                return DEFAULT_ANCHOR_DIR
            return DEFAULT_DATASET_DIR
        return v


@lru_cache(maxsize=1)
def load_config(raw: Optional[Dict[str, Any]] = None) -> TunerConfig:
    """加载配置。raw 为 None 时尝试从环境变量 CXO_TUNER_CONFIG 读取 JSON，否则用默认值。

    返回的 TunerConfig 已完整 auto_fill（缺失字段自动补齐、越界回退默认）。
    """
    data: Dict[str, Any] = {}
    if raw is None:
        from os import environ

        env = environ.get("CXO_TUNER_CONFIG")
        if env:
            import json

            try:
                data = json.loads(env)
            except json.JSONDecodeError:
                data = {}
    else:
        data = raw
    return TunerConfig.model_validate(data) if hasattr(TunerConfig, "model_validate") else TunerConfig(**data)