"""CX-O-Autonomy 动机引擎：MotivationState 四维动机状态。

四维动机（curiosity / social_need / creative_drive / fatigue）均取值 [0,1]，
与 public/schema/autonomy_state.schema.json 的 motivations 契约一致。

行为语义（**动机值越高＝越强的行动倾向**，不是"需求已被满足"）：
- curiosity 越高越想探索新知（对应 read_news / search），信息摄入后**按比例**回落
- social_need 越高越想对外表达（对应 write_post / start_live），社交互动后**按比例**回落
- creative_drive 越高越有创作冲动（对应 write_memory / write_diary）：获取素材后上升、
  **创作消费后按比例回落**（record_creation）——两侧配对避免"只升不降被钉在 1.0"
- fatigue 越高越应休息（对应 sleep），活动发生后上升、随时间衰减
- curiosity / social_need 随时间自然上升，creative_drive / fatigue 随时间自然衰减
- **四维统一收拢到 [motivation_min, 1]**（默认下限 0.02）：0 边界在四维上均不可达，
  避免"贴死 0 后该维度不再提供任何信号"的边界锁；行为回落一律**比例式**（非固定扣减）

焦点对象（对齐 autonomy_state.schema.json 的 focus）：curiosity 的**指向性维度**，
focus_topic 为"当前最想探索的具体事物"、focus_level 为对该对象的兴趣强度 [0,1]，
由 set_focus 写入（来源＝LLM 每轮自报，引擎回写），空 topic 表示暂无明确焦点。

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

# 四维动机统一的非零下限：**0 边界在四维上均不可达**。
# 动机值贴死 0 意味着该维度不再提供任何信号（"边界锁"）；curiosity / social_need
# 虽有 tick 上升可自愈，但连续同行动仍可将其压至 0，故四维统一设正下限。
_DEFAULT_MOTIVATION_MIN = 0.02

# 比例式行为系数的上界：严格小于 1，保证"按比例削去"永不直接清空任一维度
_MAX_RATIO = 0.99

# motivation_min 的上界：下限必须**严格小于**上限 1.0，否则四维会被恒钉在 1.0
# （floor == ceiling 自相矛盾，等价于另一种"退化为常量"）。
_MAX_MOTIVATION_MIN = 0.99


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
        # --- 焦点对象（curiosity 的指向性维度） ---
        focus_topic: str = "",
        focus_level: float = 0.0,
        # --- 时间驱动系数（/小时） ---
        curiosity_growth_per_hour: float = 0.05,
        social_growth_per_hour: float = 0.04,
        creative_decay_per_hour: float = 0.02,
        fatigue_decay_per_hour: float = 0.10,
        # --- 行为幅度 ---
        fatigue_activity_bump: float = 0.15,
        creative_material_bump: float = 0.10,
        creative_consume_ratio: float = 0.5,
        social_interaction_ratio: float = 0.30,
        info_ingestion_ratio: float = 0.30,
        motivation_min: float = _DEFAULT_MOTIVATION_MIN,
    ) -> None:
        """初始化动机状态：四维状态字段收拢到 [motivation_min, 1]（0 不可达），系数原样保留。"""
        self.curiosity_growth_per_hour = curiosity_growth_per_hour
        self.social_growth_per_hour = social_growth_per_hour
        self.creative_decay_per_hour = creative_decay_per_hour
        self.fatigue_activity_bump = fatigue_activity_bump
        self.fatigue_decay_per_hour = fatigue_decay_per_hour
        self.creative_material_bump = creative_material_bump
        # 比例系数收拢到 [0, _MAX_RATIO]：上界严格 < 1（不清空），负值收拢为 0（不消费）
        self.creative_consume_ratio = max(
            0.0, min(float(creative_consume_ratio), _MAX_RATIO)
        )
        self.social_interaction_ratio = max(
            0.0, min(float(social_interaction_ratio), _MAX_RATIO)
        )
        self.info_ingestion_ratio = max(0.0, min(float(info_ingestion_ratio), _MAX_RATIO))
        # 四维正下限（收拢到 [0, _MAX_MOTIVATION_MIN]：必须严格小于上限 1.0，
        # 否则四维会被恒钉在 1.0 —— floor == ceiling 属自相矛盾配置）
        self.motivation_min = max(0.0, min(_MAX_MOTIVATION_MIN, float(motivation_min)))
        # 状态字段（收拢到 [motivation_min, 1]）
        self.curiosity = self._clamp_motivation(curiosity)
        self.social_need = self._clamp_motivation(social_need)
        self.creative_drive = self._clamp_motivation(creative_drive)
        self.fatigue = self._clamp_motivation(fatigue)
        # 焦点对象（topic 去空白；level clamp 到 [0,1]）
        self.focus_topic = str(focus_topic or "").strip()
        self.focus_level = self._clamp(focus_level)

    @staticmethod
    def _clamp(value: float) -> float:
        """把数值 clamp 到 [0,1]（用于焦点强度等无下限要求的字段）。"""
        return max(0.0, min(1.0, value))

    def _clamp_motivation(self, value: float) -> float:
        """四维动机专用收拢：上限 1.0、下限 `motivation_min > 0`。

        动机贴死 0 会让该维度不再提供任何信号（"边界锁"）；尤其 `creative_drive`
        无时间自愈（tick 对其是衰减），归零后只能靠外部探索回升。正下限使 **0 在
        四维的所有写入路径（构造 / load / tick / 各行为反馈）上都不可达**。
        """
        return max(self.motivation_min, min(1.0, value))

    def tick(self, elapsed_minutes: float) -> None:
        """按流逝分钟更新时间驱动的动机变化。

        curiosity / social_need 随时间上升（rate * elapsed/60，cap 1.0）；
        creative_drive / fatigue 随时间衰减（rate * elapsed/60）。四维统一收拢到
        [motivation_min, 1]（0 不可达，见 _clamp_motivation）。
        支持小数分钟，结果确定（纯算术，无随机源）。
        """
        hours = elapsed_minutes / 60.0
        self.curiosity = self._clamp_motivation(
            self.curiosity + self.curiosity_growth_per_hour * hours
        )
        self.social_need = self._clamp_motivation(
            self.social_need + self.social_growth_per_hour * hours
        )
        self.creative_drive = self._clamp_motivation(
            self.creative_drive - self.creative_decay_per_hour * hours
        )
        self.fatigue = self._clamp_motivation(
            self.fatigue - self.fatigue_decay_per_hour * hours
        )

    def record_info_ingestion(self) -> None:
        """记录一次信息摄入：curiosity **按比例**回落（消费掉当前值的 info_ingestion_ratio）。

        比例式而非固定扣减：固定扣减在连续摄入下会把该维度压到 0 边界（0 侧锁）；
        比例式幅度随剩余值递减，叠加 `_clamp_motivation` 的正下限后 0 不可达。
        """
        self.curiosity = self._clamp_motivation(
            self.curiosity * (1.0 - self.info_ingestion_ratio)
        )

    def record_interaction(self) -> None:
        """记录一次社交互动：social_need **按比例**回落（消费掉当前值的 social_interaction_ratio）。"""
        self.social_need = self._clamp_motivation(
            self.social_need * (1.0 - self.social_interaction_ratio)
        )

    def record_activity(self) -> None:
        """记录一次活动：fatigue 上升 fatigue_activity_bump（cap 1.0）。"""
        self.fatigue = self._clamp_motivation(self.fatigue + self.fatigue_activity_bump)

    def record_material(self) -> None:
        """记录一次素材获取：creative_drive 上升 creative_material_bump（cap 1.0）。"""
        self.creative_drive = self._clamp_motivation(
            self.creative_drive + self.creative_material_bump
        )

    def record_creation(self) -> None:
        """记录一次创作消费：creative_drive 按比例回落（消费掉当前值的 creative_consume_ratio）。

        与 record_material 配对：素材获取抬升创作冲动、创作产出（write_memory /
        write_diary 成功）消费创作冲动。缺此配对时 creative_drive 只升不降
        （时间衰减仅 0.02/h），会被钉死在 1.0 上限——即"动机退化为常量"的同类缺陷。

        **比例式而非固定扣减**：固定扣减（如每次 −0.30）在素材 +0.10 的不对称下，
        连续创作会把该维度压到 0 边界，等价于把边界锁从 1.0 侧搬到 0 侧。比例式使
        幅度随剩余值递减；叠加 `_clamp_motivation` 的正下限后 0 不可达。
        """
        keep = 1.0 - self.creative_consume_ratio
        self.creative_drive = self._clamp_motivation(self.creative_drive * keep)

    def set_focus(self, topic: str, level: float = 0.0) -> None:
        """写入焦点对象（curiosity 的指向性维度）。

        来源＝LLM 每轮在规划输出中的自报，引擎回写。topic 去首尾空白（空串＝
        暂无明确焦点），level clamp 到 [0,1]。不做时间衰减——焦点仅在下一轮
        自报时更新（对齐"LLM 每轮自报"的裁决）。
        """
        self.focus_topic = str(topic or "").strip()
        self.focus_level = self._clamp(level)

    def to_focus_dict(self) -> Dict[str, object]:
        """返回焦点字典（对齐 autonomy_state.schema.json 的 focus）。"""
        return {"topic": self.focus_topic, "level": self.focus_level}

    def to_dict(self) -> Dict[str, float]:
        """返回四维动机状态字典（对齐 autonomy_state.schema.json motivations 四字段）。

        不含 focus——focus 属另一契约字段，经 to_focus_dict 单独提供；
        审计面（autonomy_audit.schema.json）只认四标量，故不可混入。
        """
        return {
            "curiosity": self.curiosity,
            "social_need": self.social_need,
            "creative_drive": self.creative_drive,
            "fatigue": self.fatigue,
        }

    def _persist_dict(self) -> Dict[str, object]:
        """落盘字典：四维动机 + 焦点对象（motivation_state.json 为运行态数据，非契约文件）。"""
        return {**self.to_dict(), "focus": self.to_focus_dict()}

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

        写入内容为四维状态字段 + focus（_persist_dict），目录不存在时自动创建（原子写）。
        """
        path = self.get_store_path(store_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, self._persist_dict())
        return str(path)

    @classmethod
    def load(cls, store_path: Union[str, Path] = "") -> "MotivationState":
        """从 motivation_state.json 恢复状态；文件不存在返回默认状态。

        恢复四维状态字段与 focus（速率/幅度系数沿用默认值）；旧版文件无 focus 键时
        按空焦点恢复（向后兼容），JSON 损坏抛 ValueError。
        """
        path = cls.get_store_path(store_path)
        if not path.exists():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"读取动机状态失败 {path}: {e}") from e
        focus = raw.get("focus") if isinstance(raw.get("focus"), dict) else {}
        return cls(
            curiosity=raw.get("curiosity", _DEFAULT_CURIOSITY),
            social_need=raw.get("social_need", _DEFAULT_SOCIAL_NEED),
            creative_drive=raw.get("creative_drive", _DEFAULT_CREATIVE_DRIVE),
            fatigue=raw.get("fatigue", _DEFAULT_FATIGUE),
            focus_topic=focus.get("topic", ""),
            focus_level=focus.get("level", 0.0),
        )
