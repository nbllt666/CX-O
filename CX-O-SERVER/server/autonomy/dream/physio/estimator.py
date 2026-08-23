"""CX-O-Dream 后端心率睡眠估计器（server/autonomy/dream/physio/estimator.py）。

接收 HR 样本流（bpm + 时间戳），在内存滑动窗口内估算清醒基线 base_hr，
输出入睡置信度 hr_sleep_confidence ∈ [0,1]。原始样本仅存在于内存窗口，
不落盘、不入记忆、不入 LLM（隐私红线 R6）。

- 无效样本（None / <=0 / >220 bpm）标记丢弃，不进入窗口、不影响置信度
- 滑动窗口默认 10 分钟（按时间戳裁剪），上限 5000 样本防内存
- base_hr 从 PhysioSignalStore 读取；base_hr_learning 开启时用窗口内高百分位
  心率作为清醒基线缓慢更新（简单实现），并持久化于 store
- 置信度：窗口均值 < base_hr×base_drop_ratio 且持续 >= base_drop_confirm_min
  分钟且窗口标准差 < hr_stability_threshold → 趋向 1.0；否则按接近程度给
  0.0-0.6 中间值；始终 [0,1]
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from server.autonomy.dream.config import PhysioConfig
from server.autonomy.dream.physio.store import PhysioSignalStore

logger = logging.getLogger(__name__)

# 无效样本上限（对齐 spec：0 或 >220 的异常样本标记丢弃）
_MAX_VALID_BPM = 220.0

# 滑动窗口默认时长（分钟）与样本上限（防内存）
_DEFAULT_WINDOW_MIN = 10
_MAX_WINDOW_SAMPLES = 5000

# 基线学习参数：高百分位（清醒基线）与缓慢更新因子、最小学习样本数
_BASE_HR_PERCENTILE = 0.9
_BASE_HR_LEARNING_RATE = 0.2
_MIN_LEARN_SAMPLES = 10

# 初始清醒基线（无学习、无持久化基线时使用）
_DEFAULT_BASE_HR = 70.0


class HeartRateSleepEstimator:
    """后端心率睡眠估计器（内存滑动窗口 + 基线学习 + 入睡置信度）。

    Args:
        config: PhysioConfig；None 时使用全默认
        store: PhysioSignalStore；None 时不持久化（仅内存计算）
        sample_window_min: 滑动窗口时长（分钟），0 时取 config 或默认 10
    """

    def __init__(
        self,
        config: Optional[PhysioConfig] = None,
        store: Optional[PhysioSignalStore] = None,
        sample_window_min: int = 0,
    ):
        self.config = config or PhysioConfig()
        self._store = store
        # 窗口时长：优先显式参数，其次 config（预留键），最后默认 10
        self._window_min = (
            sample_window_min
            if sample_window_min > 0
            else int(getattr(self.config, "sample_window_min", _DEFAULT_WINDOW_MIN))
        )
        # 滑动窗口：[(bpm, ts)]，按 ts 升序
        self._samples: List[Tuple[float, datetime]] = []
        self._base_hr: float = self._load_initial_base_hr()
        self._hr_sleep_confidence: float = 0.0
        self._updated_at: Optional[datetime] = None

    # -------------------------------------------------------------- 采样入口
    def ingest(self, bpm: Any, ts: Any) -> float:
        """接收一个 HR 样本（bpm + 时间戳），返回当前入睡置信度 [0,1]。

        无效样本（None / <=0 / >220 bpm）标记丢弃并返回当前置信度（不影响计算）。
        ts 支持 datetime / ISO 字符串 / 数值时间戳；数值 >1e11 视为 epoch 毫秒
        （自动转秒），否则视为 epoch 秒。时间戳解析失败抛 ValueError 被本方法
        吞掉并返回当前置信度（按无效样本处理，不中断估计器）。
        """
        if self._is_invalid(bpm):
            logger.debug("丢弃无效 HR 样本: %r", bpm)
            return self._hr_sleep_confidence
        try:
            sample_ts = self._parse_ts(ts)
        except (ValueError, OSError, OverflowError) as e:
            logger.debug("丢弃无效 HR 样本时间戳: %r (%s)", ts, e)
            return self._hr_sleep_confidence
        self._samples.append((float(bpm), sample_ts))
        self._trim_window()
        self._learn_base_hr()
        self._hr_sleep_confidence = self._compute_confidence()
        self._updated_at = sample_ts
        self._persist()
        return self._hr_sleep_confidence

    def get_state(self) -> Dict[str, Any]:
        """返回当前状态 {base_hr, hr_sleep_confidence, window_size, updated_at}。"""
        return {
            "base_hr": round(self._base_hr, 1),
            "hr_sleep_confidence": round(self._hr_sleep_confidence, 4),
            "window_size": len(self._samples),
            "updated_at": self._updated_at.isoformat() if self._updated_at else None,
        }

    # -------------------------------------------------------------- 样本校验/解析
    @staticmethod
    def _is_invalid(bpm: Any) -> bool:
        """无效样本判定：None / 非数值 / <=0 / >220 均为无效。"""
        if bpm is None:
            return True
        try:
            value = float(bpm)
        except (TypeError, ValueError):
            return True
        return value <= 0 or value > _MAX_VALID_BPM

    @staticmethod
    def _parse_ts(ts: Any) -> datetime:
        """时间戳解析：datetime 原样；字符串按 ISO 解析；数值 >1e11 视为
        epoch 毫秒（自动 /1000 转秒），否则视为 epoch 秒。无效类型抛 ValueError。"""
        if isinstance(ts, datetime):
            return ts
        if isinstance(ts, (int, float)):
            value = float(ts)
            if value > 1e11:  # 毫秒级时间戳（约 1973-03-03 之后）→ 转秒
                value = value / 1000.0
            return datetime.fromtimestamp(value)
        if isinstance(ts, str):
            return datetime.fromisoformat(ts)
        raise ValueError(f"无法解析 HR 样本时间戳: {ts!r}")

    # -------------------------------------------------------------- 滑动窗口
    def _trim_window(self) -> None:
        """按时间裁剪窗口（保留最近 window_min 分钟）并封顶防内存。"""
        if not self._samples:
            return
        ref = self._samples[-1][1]
        cutoff = ref - timedelta(minutes=self._window_min)
        keep = [s for s in self._samples if s[1] >= cutoff]
        if len(keep) > _MAX_WINDOW_SAMPLES:
            keep = keep[-_MAX_WINDOW_SAMPLES:]
        self._samples = keep

    # -------------------------------------------------------------- 基线
    def _load_initial_base_hr(self) -> float:
        """初始清醒基线：优先从 store 读取，其次默认 70。"""
        if self._store is not None:
            stored = self._store.get("base_hr")
            if isinstance(stored, (int, float)) and stored > 0:
                return float(stored)
        return _DEFAULT_BASE_HR

    def _learn_base_hr(self) -> None:
        """基线学习：窗口内高百分位心率作为清醒基线，缓慢更新并持久化。

        简单实现（spec 口径）：清醒期心率偏高，取窗口高百分位逼近清醒基线；
        更新因子 0.2，避免单窗口噪声剧烈抖动。
        """
        if not self.config.base_hr_learning:
            return
        if len(self._samples) < _MIN_LEARN_SAMPLES:
            return
        values = sorted(b for b, _ in self._samples)
        idx = int(round((len(values) - 1) * _BASE_HR_PERCENTILE))
        high_hr = values[idx]
        new_base = (1 - _BASE_HR_LEARNING_RATE) * self._base_hr + _BASE_HR_LEARNING_RATE * high_hr
        if new_base > 0:
            self._base_hr = round(new_base, 1)

    # -------------------------------------------------------------- 置信度
    def _compute_confidence(self) -> float:
        """计算入睡置信度 [0,1]。

        确认条件：窗口均值 < base_hr×base_drop_ratio 且持续 >= base_drop_confirm_min
        分钟且窗口标准差 < hr_stability_threshold → 1.0；否则按与下降阈值的
        接近程度给 0.0-0.6 中间值。
        """
        if not self._samples:
            return 0.0
        values = [b for b, _ in self._samples]
        mean = statistics.mean(values)
        std = statistics.pstdev(values) if len(values) > 1 else 0.0
        threshold = self._base_hr * self.config.base_drop_ratio
        sustained_min = self._sustained_drop_minutes()

        if (
            mean < threshold
            and sustained_min >= self.config.base_drop_confirm_min
            and std < self.config.hr_stability_threshold
        ):
            # 已确认入睡信号：置信度趋向 1.0
            return 1.0

        # 未完全确认：按接近程度给中间值（0.0-0.6）
        return self._intermediate_confidence(mean, threshold)

    def _sustained_drop_minutes(self) -> float:
        """最近连续低于下降阈值的样本时段跨度（分钟）。"""
        if not self._samples:
            return 0.0
        threshold = self._base_hr * self.config.base_drop_ratio
        run_start: Optional[datetime] = None
        run_end: Optional[datetime] = None
        for bpm, ts in self._samples:  # 已按 ts 升序
            if bpm < threshold:
                if run_start is None:
                    run_start = ts
                run_end = ts
            else:
                run_start = None
                run_end = None
        if run_start is None or run_end is None:
            return 0.0
        return (run_end - run_start).total_seconds() / 60.0

    @staticmethod
    def _intermediate_confidence(mean: float, threshold: float) -> float:
        """未确认入睡时的中间置信度（0.0-0.6），按与下降阈值的接近程度。"""
        if mean >= threshold:
            # 均值尚未低于阈值：0.0-0.3（越接近阈值越高）
            ratio = (mean - threshold) / max(threshold, 1.0)
            return round(0.3 * max(0.0, min(1.0, 1.0 - ratio)), 4)
        # 均值已低于阈值但未持续满确认时长：0.3-0.6
        ratio = (threshold - mean) / max(threshold, 1.0)
        return round(0.3 + 0.3 * max(0.0, min(1.0, ratio)), 4)

    # -------------------------------------------------------------- 持久化
    def _persist(self) -> None:
        """将衍生指标写入 store（异常隔离，绝不影响估计器主流程）。"""
        if self._store is None:
            return
        try:
            self._store.update(
                {
                    "base_hr": self._base_hr,
                    "hr_sleep_confidence": self._hr_sleep_confidence,
                    "device_fingerprint": self.config.device_fingerprint,
                    "updated_at": self._updated_at.isoformat() if self._updated_at else None,
                }
            )
        except Exception as e:
            logger.warning("生理状态持久化失败（异常隔离，不影响估计器）: %s", e)
