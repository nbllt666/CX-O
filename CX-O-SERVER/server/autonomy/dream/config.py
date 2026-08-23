"""CX-O-Dream 梦境引擎独立配置模型与加载/保存（对齐 server/autonomy/config.py 模式）。

- DreamConfig 为独立配置模块（人类裁决：不并入 UnifiedConfig / config_hot_reload）
- 复用 server.autonomy.config.ScheduleConfig 作为 schedule 子节（默认睡眠窗口 02:00-08:00）
- 非法 HH:MM 时间格式抛 ValueError（经 ScheduleConfig 校验）
- store_path 为空时基于 __file__ 绝对路径解析到 server/autonomy/data/，禁止相对路径/../../
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from server.autonomy.config import ScheduleConfig


class SleepConfirmationConfig(BaseModel):
    """休眠前 LLM 意图确认配置。"""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    model: str = "summary"
    timeout_sec: float = 10.0
    prompt_template: str = ""
    cooldown_seconds: int = 1800


class PhysioConfig(BaseModel):
    """CX-O-Dream 生理信号接入配置（对齐 dream_physio_config.schema.json）。

    - backend="noble" 为**信息性登记键**：标注采集路线由前端 Electron 主进程
      noble 承担，后端无对应实现、不参与任何逻辑（spec Frozen Decision 5）
    - store_raw_hr 强制 False：隐私红线 R6——原始心率禁止落盘，写 True 抛 ValueError
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    backend: str = "noble"  # 信息性登记键（前端 Electron noble 采集，后端无对应实现）
    device_name_hint: str = ""
    device_fingerprint: Optional[str] = None
    scan_timeout_sec: int = 15
    reconnect_interval_sec: int = 30
    base_drop_ratio: float = 0.88
    base_drop_confirm_min: int = 5
    hr_stability_threshold: float = 6.0
    base_hr_learning: bool = True
    store_raw_hr: bool = False

    @model_validator(mode="after")
    def _check_store_raw_hr(self) -> "PhysioConfig":
        """store_raw_hr 强制 False（隐私红线 R6：原始心率禁止落盘）。"""
        if self.store_raw_hr:
            raise ValueError("store_raw_hr 必须为 False：原始心率禁止落盘（隐私红线 R6）")
        return self


class DreamConfig(BaseModel):
    """CX-O-Dream 梦境引擎配置（对齐 dream_config.schema.json）。

    契约无必填字段：加载时缺失字段自动补齐默认值（auto_fill 语义）。
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    model: str = "summary"
    dream_temperature: float = 0.9
    candidates_per_session: int = 3
    material_window_days: int = 7
    max_material_items: int = 20
    min_lucidity: float = 0.3
    dream_ttl_hours: int = 72
    purge_threshold: float = 0.1
    confirmed_importance: float = 0.4
    surface_on_wake: bool = True
    surface_probability: float = 0.5
    max_surface_per_day: int = 1
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    physio: PhysioConfig = Field(default_factory=PhysioConfig)
    sleep_confirmation: SleepConfirmationConfig = Field(default_factory=SleepConfirmationConfig)


def resolve_store_dir(store_path: str = "") -> str:
    """解析存储目录：store_path 为空时基于 __file__ 绝对路径解析到 server/autonomy/data/。"""
    return store_path or str(Path(__file__).resolve().parent.parent / "data")


def load_config(store_path: str = "") -> DreamConfig:
    """从 store_path/dream_config.json 读取配置。

    缺失字段自动补齐默认值；文件不存在时返回全默认实例。
    store_path 为空表示使用默认解析目录（server/autonomy/data/）。
    """
    store = resolve_store_dir(store_path)
    cfg_path = Path(store) / "dream_config.json"
    if not cfg_path.exists():
        return DreamConfig()
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"读取梦境配置失败 {cfg_path}: {e}") from e
    return DreamConfig.model_validate(raw)


def save_config(config: DreamConfig, store_path: str = "") -> str:
    """将配置写入 store_path/dream_config.json，返回写入路径。"""
    store = resolve_store_dir(store_path)
    cfg_path = Path(store) / "dream_config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, ensure_ascii=False, indent=2)
    return str(cfg_path)
