"""CXO-EvalKit 配置。

pydantic BaseModel 承载全部配置，缺失字段自动补默认值（auto_fill）。
API key 类字段仅存于 config 对象，不落报告不入库（to_safe_dict 剥离）。
禁止在业务代码中硬编码配置参数。
"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# 基于 __file__ 解析 CXO-EvalKit 项目根（禁止相对路径漂移，统一从本文件锚定）
EVALKIT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(EVALKIT_ROOT, "config.json")


class TargetConfig(BaseModel):
    """被测主服务（CX-O-SERVER）连接配置。"""

    base_url: str = "http://host.docker.internal:8000"
    admin_api_key: str = ""  # 调主服务 admin 端点用；key 不入报告不入库


class JudgeConfig(BaseModel):
    """LLM-as-judge 配置（OpenAI 兼容 chat/completions）。"""

    api_base: str = ""  # 空 → 默认跟随 target 同源（target.base_url 的 /v1/chat/completions）
    model: str = ""
    api_key: str = ""
    timeout_seconds: float = 60


class MemoryThresholds(BaseModel):
    """记忆维度通过阈值。"""

    retention_1y_min: float = 0.6
    permanent_retention: float = 1.0
    reactivation_must_beat_control: bool = True


class LatencyThresholds(BaseModel):
    """延迟维度通过阈值。"""

    p95_ms: float = 2000
    regression_pct: float = 20
    ws_p95_ms: float = 800  # 全双工主指标：容器分句定稿（asr_final）→ 首包 TTS 音频 P95，服务端 VAD 不参与判定


class QualityThresholds(BaseModel):
    """质量维度通过阈值。"""

    avg_min: float = 3.5


class ThresholdsConfig(BaseModel):
    """各维度通过阈值汇总。"""

    memory: MemoryThresholds = Field(default_factory=MemoryThresholds)
    latency: LatencyThresholds = Field(default_factory=LatencyThresholds)
    quality: QualityThresholds = Field(default_factory=QualityThresholds)


class MemoryDecayConfig(BaseModel):
    """记忆衰减曲线探针配置。

    interval_days 默认长期年轴：1 月 / 6 月 / 1 年 / 3 年，可扩展至 5 / 10 年。
    """

    interval_days: List[int] = Field(default_factory=lambda: [30, 180, 365, 1095])
    reactivation_visit_every_days: int = 30  # 再激活组按月重访


class WSFullDuplexConfig(BaseModel):
    """全双工语音链路探测参数（WS voice.dual_stream：音频流→ASR→LLM→TTS 首包）。

    utterance_wav 为空时使用打包资产 assets/utterance_16k.wav（16k/mono/16bit）。
    """

    enabled: bool = True
    turns: int = 3
    utterance_wav: str = ""
    frame_ms: int = 30
    turn_timeout_seconds: float = 90
    real_time_pacing: bool = True  # 按 30ms 帧实时节奏发送（VAD 时序真实性）


class LatencyProbeConfig(BaseModel):
    """延迟探针执行参数。"""

    rounds: int = 10
    probe_timeout_seconds: float = 120
    concurrency_levels: List[int] = Field(default_factory=lambda: [1])
    baseline_run_id: Optional[str] = None  # 基线 run（探针集一致时输出对比）
    ws_full_duplex: WSFullDuplexConfig = Field(default_factory=WSFullDuplexConfig)


class MockConfig(BaseModel):
    """Mock 模式：内置 stub target + stub judge（无需真实主服务与 LLM 全链路跑通）。"""

    enabled: bool = False
    chat_delay_ms: int = 0  # stub chat 附加延迟（ms），用于延迟 suite 的分布可测性


class EvalConfig(BaseModel):
    """CXO-EvalKit 全量配置。缺失字段由 pydantic default 自动补齐。"""

    target: TargetConfig = Field(default_factory=TargetConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    memory_decay: MemoryDecayConfig = Field(default_factory=MemoryDecayConfig)
    latency: LatencyProbeConfig = Field(default_factory=LatencyProbeConfig)
    mock: MockConfig = Field(default_factory=MockConfig)
    data_dir: str = "data"

    def to_safe_dict(self) -> Dict[str, Any]:
        """剥离 API key 后返回 dict，供日志/落盘/入库快照使用。"""
        data = self.model_dump()
        data["target"]["admin_api_key"] = ""
        data["judge"]["api_key"] = ""
        return data


def merge_overrides(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """深合并配置字典（overrides 优先），不污染 base。"""
    merged = copy.deepcopy(base)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_overrides(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: Optional[str] = None) -> EvalConfig:
    """加载配置。path 为 None 时依次尝试：CXO-EvalKit/config.json → 纯默认值。

    缺失字段由 pydantic default 自动补全；API key 类字段仅存于返回的 config 对象。
    """
    data: Dict[str, Any] = {}
    config_path = path
    if config_path is None and os.path.exists(DEFAULT_CONFIG_PATH):
        config_path = DEFAULT_CONFIG_PATH
    if config_path is not None:
        with open(config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError(f"配置文件必须是 JSON 对象: {config_path}")
        data = loaded
    return EvalConfig.model_validate(data)
