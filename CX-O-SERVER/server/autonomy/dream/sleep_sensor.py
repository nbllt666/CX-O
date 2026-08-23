"""CX-O-Dream SleepSensor 融合状态机（server/autonomy/dream/sleep_sensor.py）。

S1-S9 多路睡眠信号融合：注册 9 路信号 provider（S1 输入静默 / S2 语音静默 /
S3 呼吸鼾声 / S4 显式睡眠语 / S5 视觉闭眼 / S6 系统锁屏 / S7 时间先验 /
S8 桌宠状态 / S9 生理心率），按可用信号动态归一权重计算 confidence，
输出 AWAKE / DROWSY / ASLEEP / AWAY 四态。

- 动态归一：available 信号权重归一化（总权重归一），confidence = Σ(w_i·v_i)/Σw_i
- S4 短路（GN-004 B15 修正）：S4.available 且 value>=0.5（命中显式睡眠语）→
  直接 ASLEEP、跳过归一化；未命中的 S4 不参与归一（避免 1.0 权重稀释其余信号）
- 状态机：confidence>=0.8 → ASLEEP；>=0.5 → DROWSY；S6 锁屏且 S9 持续无样本
  超阈值 → AWAY；否则 AWAKE
- 交叉验证：S9 心率下降（value>=0.7）但 S1 行为活跃（value<0.3）→ 强制 AWAKE；
  S9 缺席（不可用）时 S9 weight 0 自动归一，退化为纯时间/行为判定

无源信号（S3/S5/S8）：available=False、weight 0、定义 set_source() 接入接口，
源就绪后自动启用。本模块不做任何文件 IO，禁止相对路径。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

class SleepSensorState:
    """SleepSensor 状态常量定义。"""
    AWAKE = "AWAKE"
    DROWSY = "DROWSY"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    ENTERING_SLEEP = "ENTERING_SLEEP"
    ASLEEP = "ASLEEP"
    AWAY = "AWAY"


# 信号注册表（spec §5 权重表）：(编号, 中文标签, 权重)。S4=1.0 为短路信号。
_SIGNAL_WEIGHTS: Tuple[Tuple[str, str, float], ...] = (
    ("S1", "输入静默", 0.15),
    ("S2", "语音静默", 0.10),
    ("S3", "呼吸鼾声", 0.22),
    ("S4", "显式睡眠语", 1.0),
    ("S5", "视觉闭眼", 0.20),
    ("S6", "系统锁屏", 0.15),
    ("S7", "时间先验", 0.05),
    ("S8", "桌宠状态", 0.03),
    ("S9", "生理心率", 0.40),
)

# 状态机置信度阈值：confidence >= ASLEEP / >= DROWSY
_CONF_ASLEEP = 0.8
_CONF_DROWSY = 0.5

# 短路与交叉验证阈值
_S4_FIRE_THRESHOLD = 0.5  # S4 命中阈值（value>=0.5 触发短路）
_HR_DOWN_THRESHOLD = 0.7  # S9 心率下降判定（value>=0.7）
_ACTIVE_THRESHOLD = 0.3   # S1 行为活跃判定（value<0.3 → 键鼠活跃）

# S1/S6 系统静默默认阈值（秒）：满静默 / 锁屏
_DEFAULT_IDLE_THRESHOLDS: Dict[str, float] = {
    "s1_full_silent_sec": 600.0,  # 10 分钟无输入 → S1 满值
    "s6_lock_sec": 900.0,         # 15 分钟无操作 → S6 满值（视为锁屏）
}

# S2 语音静默满值阈值（秒）
_VOICE_SILENT_SEC = 300.0

# 默认保持/陈旧阈值（分钟）与时间先验衰减跨度（小时）
_DEFAULT_S4_HOLD_MIN = 10.0
_DEFAULT_AWAY_HR_STALE_MIN = 30.0
_DEFAULT_TIME_PRIOR_SPAN_HOURS = 4.0


@dataclass
class SleepSignalProvider:
    """单路睡眠信号 provider。

    name: 信号编号（S1-S9）；label: 中文描述；weight: 基础权重；
    value: 当前信号值 [0,1]；available: 是否有数据源接入。
    set_source(): S3/S5/S8 无源 provider 的源注入接口（接线后自动可用）；
    update(): 更新信号值（钳制 [0,1]）并标记可用。
    """

    name: str
    label: str
    weight: float
    value: float = 0.0
    available: bool = False
    source: Optional[Callable[[], float]] = None

    def set_source(self, fn: Callable[[], float]) -> None:
        """注入外部取值函数并标记可用（无源信号的接入点，源就绪后自动启用）。"""
        self.source = fn
        self.available = True

    def update(self, value: float) -> None:
        """更新信号值（钳制到 [0,1]，非法值归 0）并标记可用。"""
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 0.0
        self.value = max(0.0, min(1.0, v))
        self.available = True


class SleepSensor:
    """S1-S9 多路睡眠信号融合状态机（AWAKE/DROWSY/ASLEEP/AWAY）。

    Args:
        now_fn: 当前时间提供函数（默认 datetime.now，便于测试注入固定时钟）
        conf_asleep: ASLEEP 置信度阈值（默认 0.8）
        conf_drowsy: DROWSY 置信度阈值（默认 0.5）
        s4_hold_min: S4 短路保持时长（分钟，默认 10）
        away_hr_stale_min: S9 无样本判定离开的超时（分钟，默认 30）
        time_prior_span_hours: S7 时间先验窗口外衰减跨度（小时，默认 4）
    """

    def __init__(
        self,
        now_fn: Optional[Callable[[], datetime]] = None,
        conf_asleep: float = _CONF_ASLEEP,
        conf_drowsy: float = _CONF_DROWSY,
        s4_hold_min: float = _DEFAULT_S4_HOLD_MIN,
        away_hr_stale_min: float = _DEFAULT_AWAY_HR_STALE_MIN,
        time_prior_span_hours: float = _DEFAULT_TIME_PRIOR_SPAN_HOURS,
    ):
        self._now_fn = now_fn or datetime.now
        self._conf_asleep = conf_asleep
        self._conf_drowsy = conf_drowsy
        self._s4_hold_min = s4_hold_min
        self._away_hr_stale_min = away_hr_stale_min
        self._time_prior_span_hours = time_prior_span_hours

        # 注册 9 路信号 provider（S4=1.0 短路）
        self._providers: List[SleepSignalProvider] = [
            SleepSignalProvider(name=n, label=label, weight=w)
            for n, label, w in _SIGNAL_WEIGHTS
        ]

        # 内部状态
        self._s4_hit_at: Optional[datetime] = None
        self._last_hr_at: Optional[datetime] = None
        self._state: str = "AWAKE"
        self._confidence: float = 0.0
        self._updated_at: Optional[datetime] = None

    def wake_up(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """显式唤醒接口：重置睡眠与短路状态，强制将状态切换为 AWAKE。

        清除 S4 命中时刻、重置 S4 为 0，并将内部状态置为 AWAKE。
        Returns:
            {state: 'AWAKE', confidence: float, updated_at: str}
        """
        now = now or self._now_fn()
        self._s4_hit_at = None
        s4 = self._provider("S4")
        s4.value = 0.0
        return self._set_state(SleepSensorState.AWAKE, 0.0, now)

    def transition_state(self, state: str, confidence: Optional[float] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
        """显式流转到指定状态（如 PENDING_CONFIRMATION / ENTERING_SLEEP / ASLEEP / AWAKE 等）。"""
        now = now or self._now_fn()
        conf = self._confidence if confidence is None else confidence
        return self._set_state(state, conf, now)

    # -------------------------------------------------------------- 信号注入
    def set_hr_confidence(self, conf: float) -> None:
        """注入 S9 生理心率置信度 [0,1]（来自 HeartRateSleepEstimator）。"""
        self._provider("S9").update(conf)
        self._last_hr_at = self._now_fn()

    def set_system_idle(
        self, idle_sec: float, thresholds: Optional[Dict[str, float]] = None
    ) -> None:
        """注入系统空闲时长（秒）驱动 S1 输入静默 / S6 系统锁屏。

        thresholds 可选覆盖 {"s1_full_silent_sec", "s6_lock_sec"}（秒），
        超过对应阈值信号值取 1.0，否则按比例。来自前端 POST /physio/state 的
        system_idle_sec。
        """
        th = {**_DEFAULT_IDLE_THRESHOLDS, **(thresholds or {})}
        self._provider("S1").update(min(1.0, idle_sec / th["s1_full_silent_sec"]))
        self._provider("S6").update(min(1.0, idle_sec / th["s6_lock_sec"]))

    def set_voice_activity(self, recent_sec: Optional[float]) -> None:
        """注入最近语音活动秒数驱动 S2 语音静默。

        recent_sec 为 None（无语音流水线）时 S2 置为不可用（available=False）；
        否则值随静默时长升高（满静默阈值 _VOICE_SILENT_SEC=300s）。
        """
        s2 = self._provider("S2")
        if recent_sec is None:
            s2.available = False
            s2.value = 0.0
            return
        s2.update(min(1.0, recent_sec / _VOICE_SILENT_SEC))

    def set_sleep_speech(self, hit: bool) -> None:
        """注入 S4 显式睡眠语命中信号（聊天关键词：睡了/困了/去睡了等）。

        hit=True 时置值 1.0 并记录命中时刻（短时保持 s4_hold_min 分钟）；
        hit=False 仅标记源已接线，不重置保持窗口。
        """
        s4 = self._provider("S4")
        s4.available = True  # 睡眠语源已接线
        if hit:
            s4.update(1.0)
            self._s4_hit_at = self._now_fn()

    def set_time_prior(self, now: datetime, circadian: Any) -> None:
        """注入 S7 时间先验：circadian 睡眠窗口内 ≈1，窗口外按距边界小时数递减。"""
        self._provider("S7").update(self._time_prior_value(now, circadian))

    def set_external_source(self, name: str, fn: Callable[[], float]) -> None:
        """为 S3/S5/S8 无源 provider 注入外部取值函数（接线后自动可用）。"""
        self._provider(name).set_source(fn)

    # -------------------------------------------------------------- 融合评估
    def evaluate(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """计算当前融合状态，返回 {state, confidence, updated_at}。"""
        now = now or self._now_fn()
        self._refresh_sources(now)
        self._decay_s4(now)

        # S4 短路：命中显式睡眠语 → 直接 ASLEEP、跳过归一化
        s4 = self._provider("S4")
        if s4.available and s4.value >= _S4_FIRE_THRESHOLD:
            return self._set_state("ASLEEP", 1.0, now)

        # 动态归一：available 信号权重归一化
        available = self._available_for_fusion()
        total_weight = sum(p.weight for p in available)
        if total_weight > 0:
            confidence = sum(p.weight * p.value for p in available) / total_weight
        else:
            confidence = 0.0

        # 交叉验证：生理下降但行为活跃 → 强制 AWAKE（避免静坐看视频误判入睡）
        s9 = self._provider("S9")
        s1 = self._provider("S1")
        if s9.value >= _HR_DOWN_THRESHOLD and s1.available and s1.value < _ACTIVE_THRESHOLD:
            return self._set_state("AWAKE", confidence, now)

        # AWAY：系统锁屏且 S9 持续无样本超阈值（长时间无信号 → 用户离开）
        s6 = self._provider("S6")
        if s6.available and s6.value >= 1.0 and self._hr_stale(now):
            return self._set_state("AWAY", confidence, now)

        # 阈值判定
        if confidence >= self._conf_asleep:
            state = "ASLEEP"
        elif confidence >= self._conf_drowsy:
            state = "DROWSY"
        else:
            state = "AWAKE"
        return self._set_state(state, confidence, now)

    def snapshot(self) -> Dict[str, Any]:
        """返回当前状态快照 {state, confidence, signals, updated_at}。"""
        state = self.evaluate()
        state["signals"] = [
            {
                "name": p.name,
                "weight": p.weight,
                "value": round(p.value, 4),
                "available": p.available,
            }
            for p in self._providers
        ]
        return state

    def normalized_weights(self) -> Dict[str, float]:
        """返回参与动态归一信号的归一化权重映射（总权重=1），供验证/调试。"""
        available = self._available_for_fusion()
        total = sum(p.weight for p in available)
        if total <= 0:
            return {}
        return {p.name: round(p.weight / total, 6) for p in available}

    # -------------------------------------------------------------- 内部
    def _provider(self, name: str) -> SleepSignalProvider:
        """按编号取 provider，未知编号抛 KeyError。"""
        for p in self._providers:
            if p.name == name:
                return p
        raise KeyError(f"未知信号 provider: {name!r}")

    def _available_for_fusion(self) -> List[SleepSignalProvider]:
        """参与动态归一的信号：available 且未命中的短路信号 S4 除外。"""
        return [
            p
            for p in self._providers
            if p.available and not (p.name == "S4" and p.value < _S4_FIRE_THRESHOLD)
        ]

    def _refresh_sources(self, now: datetime) -> None:
        """拉取外部 source（S3/S5/S8 等）最新值，异常隔离不影响主流程。"""
        for p in self._providers:
            if p.source is None:
                continue
            try:
                p.update(p.source())
            except Exception as e:
                logger.warning("信号源 %s 取值失败（异常隔离）: %s", p.name, e)

    def _decay_s4(self, now: datetime) -> None:
        """S4 短路值短时保持：命中超 s4_hold_min 分钟后衰减回 0。"""
        if self._s4_hit_at is None:
            return
        if (now - self._s4_hit_at).total_seconds() / 60.0 >= self._s4_hold_min:
            self._provider("S4").value = 0.0

    def _hr_stale(self, now: datetime) -> bool:
        """S9 持续无样本判定：从未有样本或距最后样本超 away_hr_stale_min。"""
        if self._last_hr_at is None:
            return True
        return (now - self._last_hr_at).total_seconds() / 60.0 >= self._away_hr_stale_min

    def _time_prior_value(self, now: datetime, circadian: Any) -> float:
        """S7 时间先验：circadian 睡眠窗口内 1.0，窗口外按距边界小时数衰减。"""
        dist_h = self._sleep_window_distance_hours(now, circadian)
        if dist_h <= 0:
            return 1.0
        return max(0.0, 1.0 - dist_h / self._time_prior_span_hours)

    @staticmethod
    def _sleep_window_distance_hours(now: datetime, circadian: Any) -> float:
        """now 距最近睡眠窗口边界的小时数（窗口内返回 0，支持跨午夜）。"""
        sleep_t = circadian.sleep_time
        wake_t = circadian.wake_time
        day = now.date()
        candidates: List[Tuple[datetime, datetime]] = []
        if sleep_t < wake_t:
            candidates.append((datetime.combine(day, sleep_t), datetime.combine(day, wake_t)))
        else:
            # 跨午夜窗口：昨夜入睡→今晨醒，及今晚入睡→明晨醒
            candidates.append(
                (
                    datetime.combine(day - timedelta(days=1), sleep_t),
                    datetime.combine(day, wake_t),
                )
            )
            candidates.append(
                (
                    datetime.combine(day, sleep_t),
                    datetime.combine(day + timedelta(days=1), wake_t),
                )
            )
        best: Optional[float] = None
        for start, end in candidates:
            if start <= now < end:
                return 0.0
            if now < start:
                delta = start - now
            else:
                delta = now - end
            dist_h = delta.total_seconds() / 3600.0
            best = dist_h if best is None else min(best, dist_h)
        return best or 0.0

    def _set_state(self, state: str, confidence: float, now: datetime) -> Dict[str, Any]:
        """落定状态并返回 {state, confidence, updated_at}。"""
        self._state = state
        self._confidence = round(confidence, 4)
        self._updated_at = now
        return {
            "state": self._state,
            "confidence": self._confidence,
            "updated_at": self._updated_at.isoformat(),
        }


def wire_sleep_sensor(
    sensor: SleepSensor,
    circadian: Any,
    estimator: Optional[Any] = None,
    voice_recent_sec: Optional[float] = None,
    idle_sec: float = 0.0,
    idle_thresholds: Optional[Dict[str, float]] = None,
    sleep_speech_hit: bool = False,
    now: Optional[datetime] = None,
) -> SleepSensor:
    """装配真实信号源到 SleepSensor（Task 3 SubTask 3.2/3.3 真实源接线）。

    - S7 时间先验：circadian.is_sleep_time(now)（窗口内 1.0，窗口外递减）
    - S9 生理心率：estimator.get_state().hr_sleep_confidence
      （仅当估计器窗口内有真实样本时刷新，保持陈旧判定）
    - S1/S6 系统静默：idle_sec（前端 POST /physio/state 的 system_idle_sec）
    - S2 语音静默：voice_recent_sec（默认 None → available=False）
    - S4 显式睡眠语：sleep_speech_hit（聊天关键词命中置 1）
    - S3/S5/S8 无源 provider：available=False、weight 0，暴露 set_source 接入点
    """
    now = now or datetime.now()
    # S7 时间先验
    sensor.set_time_prior(now, circadian)
    # S9 生理心率（仅估计器有真实样本时刷新，避免伪造新鲜度）
    if estimator is not None:
        try:
            est_state = estimator.get_state()
            if est_state.get("window_size", 0) > 0:
                sensor.set_hr_confidence(est_state.get("hr_sleep_confidence", 0.0))
        except Exception as e:
            logger.warning("心率置信度读取失败（S9 降级为 weight 0）: %s", e)
    # S1/S6 系统静默
    sensor.set_system_idle(idle_sec, idle_thresholds)
    # S2 语音静默（None → 不可用）
    sensor.set_voice_activity(voice_recent_sec)
    # S4 显式睡眠语
    sensor.set_sleep_speech(sleep_speech_hit)
    # S3/S5/S8 无源 provider：保持 available=False、weight 0，set_source 接口就绪
    return sensor
