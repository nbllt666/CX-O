"""CX-O-Autonomy 动机引擎：MotivationState 四维动机状态。

四维动机（curiosity / social_need / creative_drive / fatigue）均取值 [0,1]，
与 public/schema/autonomy_state.schema.json 的 motivations 契约一致。

行为语义：
- curiosity / social_need 随时间自然上升（信息摄入 / 社交互动会消耗下降）
- creative_drive / fatigue 随时间自然衰减（获取素材提升创造欲 / 活动提升疲劳）
- 所有状态字段经 clamp 保证落在 [0,1]，超界自动收拢

持久化：save/load 以 JSON（motivation_state.json）往返，目录由 get_store_path
基于给定 store_path 或默认目录 server/autonomy/data/（__file__ 绝对路径解析）确定，
禁止相对路径 / ../.. / ../../ 形式。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Union

from server.autonomy._atomic_io import atomic_write_json

# 默认初始动机（对齐 manager.py 的 Motivations 初始值）
_DEFAULT_CURIOSITY = 0.2
_DEFAULT_SOCIAL_NEED = 0.2
_DEFAULT_CREATIVE_DRIVE = 0.2
_DEFAULT_FATIGUE = 0.0


class MotivationState:
    """CX-O-Autonomy 四维动机状态（curiosity / social_need / creative_drive / fatigue）。

    构造参数中的增长/衰减/幅度系数带默认值，便于测试注入；状态字段在构造与
    每次行为记录后均 clamp 到 [0,1]。
    """

    def __init__(
        self,
        curiosity: float = _DEFAULT_CURIOSITY,
        social_need: float = _DEFAULT_SOCIAL_NEED,
        creative_drive: float = _DEFAULT_CREATIVE_DRIVE,
        fatigue: float = _DEFAULT_FATIGUE,
        # --- 时间驱动系数（/小时） ---
        curiosity_growth_per_hour: float = 0.05,
        social_growth_per_hour: float = 0.04,
        creative_decay_per_hour: float = 0.02,
        fatigue_decay_per_hour: float = 0.10,
        # --- 行为幅度 ---
        fatigue_activity_bump: float = 0.15,
        creative_material_bump: float = 0.10,
        social_interaction_drop: float = 0.30,
        info_ingestion_drop: float = 0.30,
    ) -> None:
        """初始化动机状态：状态字段 clamp 到 [0,1]，系数参数原样保留。"""
        self.curiosity_growth_per_hour = curiosity_growth_per_hour
        self.social_growth_per_hour = social_growth_per_hour
        self.creative_decay_per_hour = creative_decay_per_hour
        self.fatigue_activity_bump = fatigue_activity_bump
        self.fatigue_decay_per_hour = fatigue_decay_per_hour
        self.creative_material_bump = creative_material_bump
        self.social_interaction_drop = social_interaction_drop
        self.info_ingestion_drop = info_ingestion_drop
        # 状态字段（clamp 到 [0,1]）
        self.curiosity = self._clamp(curiosity)
        self.social_need = self._clamp(social_need)
        self.creative_drive = self._clamp(creative_drive)
        self.fatigue = self._clamp(fatigue)

    @staticmethod
    def _clamp(value: float) -> float:
        """把数值 clamp 到 [0,1]：超 1 收拢为 1，减到负收拢为 0。"""
        return max(0.0, min(1.0, value))

    def tick(self, elapsed_minutes: float) -> None:
        """按流逝分钟更新时间驱动的动机变化。

        curiosity / social_need 随时间上升（rate * elapsed/60，cap 1.0）；
        creative_drive / fatigue 随时间衰减（rate * elapsed/60，floor 0）。
        支持小数分钟，结果确定（纯算术，无随机源）。
        """
        hours = elapsed_minutes / 60.0
        self.curiosity = self._clamp(
            self.curiosity + self.curiosity_growth_per_hour * hours
        )
        self.social_need = self._clamp(
            self.social_need + self.social_growth_per_hour * hours
        )
        self.creative_drive = self._clamp(
            self.creative_drive - self.creative_decay_per_hour * hours
        )
        self.fatigue = self._clamp(
            self.fatigue - self.fatigue_decay_per_hour * hours
        )

    def record_info_ingestion(self) -> None:
        """记录一次信息摄入：curiosity 下降 info_ingestion_drop（floor 0）。"""
        self.curiosity = self._clamp(self.curiosity - self.info_ingestion_drop)

    def record_interaction(self) -> None:
        """记录一次社交互动：social_need 下降 social_interaction_drop（floor 0）。"""
        self.social_need = self._clamp(self.social_need - self.social_interaction_drop)

    def record_activity(self) -> None:
        """记录一次活动：fatigue 上升 fatigue_activity_bump（cap 1.0）。"""
        self.fatigue = self._clamp(self.fatigue + self.fatigue_activity_bump)

    def record_material(self) -> None:
        """记录一次素材获取：creative_drive 上升 creative_material_bump（cap 1.0）。"""
        self.creative_drive = self._clamp(self.creative_drive + self.creative_material_bump)

    def to_dict(self) -> Dict[str, float]:
        """返回四维动机状态字典（对齐 autonomy_state.schema.json motivations 四字段）。"""
        return {
            "curiosity": self.curiosity,
            "social_need": self.social_need,
            "creative_drive": self.creative_drive,
            "fatigue": self.fatigue,
        }

    @staticmethod
    def get_store_path(store_path: Union[str, Path] = "") -> Path:
        """解析 motivation_state.json 完整路径。

        store_path 非空时视为存储目录；为空时基于 __file__ 绝对路径解析到
        server/autonomy/data/（parent.parent.parent / "data"），禁止相对路径/../..。
        """
        if store_path:
            base = Path(store_path)
        else:
            base = Path(__file__).resolve().parents[2] / "data"
        return base / "motivation_state.json"

    def save(self, store_path: Union[str, Path] = "") -> str:
        """将当前状态写入 motivation_state.json，返回写入文件路径。

        写入内容为 to_dict()（四维状态字段），目录不存在时自动创建（原子写）。
        """
        path = self.get_store_path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, self.to_dict())
        return str(path)

    @classmethod
    def load(cls, store_path: Union[str, Path] = "") -> "MotivationState":
        """从 motivation_state.json 恢复状态；文件不存在返回默认状态。

        只恢复四维状态字段（速率/幅度系数沿用默认值），JSON 损坏抛 ValueError。
        """
        path = cls.get_store_path(store_path)
        if not path.exists():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"读取动机状态失败 {path}: {e}") from e
        return cls(
            curiosity=raw.get("curiosity", _DEFAULT_CURIOSITY),
            social_need=raw.get("social_need", _DEFAULT_SOCIAL_NEED),
            creative_drive=raw.get("creative_drive", _DEFAULT_CREATIVE_DRIVE),
            fatigue=raw.get("fatigue", _DEFAULT_FATIGUE),
        )
