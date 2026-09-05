"""语音链路延迟采集器（per-turn 结构化打点 + 环形缓冲 + P50/P95 聚合）。

事件流（spec Task 4，双流式语音链路）：
    speech_end → asr_final → llm_start → llm_first_token(TTFT) → tts_first_chunk → turn_done

段延迟定义（ms）：
    - asr       = speech_end → asr_final
    - ttft      = llm_start → llm_first_token
    - tts_first = asr_final → tts_first_chunk
    - e2e       = speech_end → tts_first_chunk

轮次（turn）生命周期：
    - speech_end 开新轮；若该 client 已有未结算旧轮（缺 turn_done），旧轮作废丢弃
    - turn_done 到达即结算入环形缓冲（缺任何一侧时间戳的段记 None）
    - 超时（默认 120s 无事件进展）的轮自动作废（懒清扫，不入缓冲）

双流式时序说明（为何事件可能先于 speech_end 到达）：
    主路径由 ASR Partial 驱动 Speculative Prefill——llm_start / llm_first_token /
    tts_first_chunk 常在 speech_end **之前**产生。因此除 speech_end 之外的
    事件若在无轮次时到达，会隐式开轮并随随后的 speech_end 并入同一轮；
    speech_end 到达时轮内已有 speech_end 槽位则视为上一轮未结算，作废后开新轮。
    命中 e2e/tts_first 为负序（回复先于语音结束开始）时按 0 记录——
    表示"该段在参考点之前已完成"，避免仪表盘出现负延迟。

设计红线：
    - record / record_current / summary / recent / buffer_size 全部吞异常，
      永不向语音主链路抛出（采集失败只能影响指标，不能影响通话）
    - 仅依赖标准库（无外部依赖），threading.Lock 保护全部可变状态
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

# 环形缓冲默认容量（保留最近 200 轮已结算样本）
DEFAULT_BUFFER_SIZE = 200
# 轮次超时作废阈值（秒）：超过该时长无任何事件进展的轮直接丢弃
DEFAULT_TURN_TIMEOUT_S = 120.0


class VoiceLatencyEvent(str, Enum):
    """语音链路打点事件枚举。"""

    SPEECH_END = "speech_end"
    ASR_FINAL = "asr_final"
    LLM_START = "llm_start"
    LLM_FIRST_TOKEN = "llm_first_token"
    TTS_FIRST_CHUNK = "tts_first_chunk"
    TURN_DONE = "turn_done"


# 参与段延迟计算的事件对（段名 → (起点事件, 终点事件)）
_SEGMENT_DEFS: Dict[str, tuple] = {
    "asr": (VoiceLatencyEvent.SPEECH_END, VoiceLatencyEvent.ASR_FINAL),
    "ttft": (VoiceLatencyEvent.LLM_START, VoiceLatencyEvent.LLM_FIRST_TOKEN),
    "tts_first": (VoiceLatencyEvent.ASR_FINAL, VoiceLatencyEvent.TTS_FIRST_CHUNK),
    "e2e": (VoiceLatencyEvent.SPEECH_END, VoiceLatencyEvent.TTS_FIRST_CHUNK),
}

# asr_final 采用"最后一次覆盖"策略：Feature B 长句内部停顿会产生中段 final，
# 最接近语音结束的那次 final 才是与 speech_end 配对的完整识别结果。
_LAST_WINS_EVENTS = {VoiceLatencyEvent.ASR_FINAL}


def _percentile(sorted_values: List[float], p: float) -> Optional[float]:
    """线性插值百分位数（无外部依赖）。sorted_values 须为升序列表，p ∈ [0, 100]。"""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(float(sorted_values[0]), 2)
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(float(sorted_values[int(k)]), 2)
    return round(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f), 2)


@dataclass
class _ActiveTurn:
    """进行中的轮次：按事件累积时间戳（wall clock 秒）。"""

    client_id: str
    events: Dict[VoiceLatencyEvent, float] = field(default_factory=dict)
    last_event_ts: float = 0.0


@dataclass
class TurnRecord:
    """已结算轮次样本（环形缓冲存储单元）。"""

    client_id: str
    settled_at: float
    # 各段延迟 ms（缺端点记 None）：asr / ttft / tts_first / e2e
    segments: Dict[str, Optional[float]]
    # 事件名 → 时间戳（wall clock 秒，供明细排查）
    events: Dict[str, float]

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id,
            "settled_at": self.settled_at,
            "segments": dict(self.segments),
            "events": dict(self.events),
        }


class VoiceLatencyTracker:
    """per-client per-turn 语音链路延迟采集器。

    Args:
        maxlen: 环形缓冲容量（默认 200）
        turn_timeout_s: 轮次超时作废阈值（默认 120s）
        clock: 时间源（默认 time.time，测试可注入假时钟）
    """

    def __init__(
        self,
        maxlen: int = DEFAULT_BUFFER_SIZE,
        turn_timeout_s: float = DEFAULT_TURN_TIMEOUT_S,
        clock: Optional[Callable[[], float]] = None,
    ):
        self._maxlen = maxlen
        self._turn_timeout_s = turn_timeout_s
        self._clock = clock or time.time
        self._lock = threading.Lock()
        # 已结算轮次环形缓冲（仅 turn_done 正常完成的轮进入）
        self._buffer: deque = deque(maxlen=maxlen)
        # client_id → 进行中轮次
        self._active: Dict[str, _ActiveTurn] = {}

    # ------------------------------------------------------------------
    # 打点入口（永不抛出）
    # ------------------------------------------------------------------
    def record(
        self,
        client_id: str,
        event: Union[VoiceLatencyEvent, str],
        ts: Optional[float] = None,
    ) -> None:
        """记录一次事件打点。任何异常内部吞掉，绝不向语音主链路抛出。"""
        try:
            self._record_impl(client_id, event, ts)
        except Exception:  # noqa: BLE001 —— 采集失败静默降级，零阻断
            pass

    def record_current(
        self, event: Union[VoiceLatencyEvent, str], ts: Optional[float] = None
    ) -> None:
        """以 contextvar 中的当前语音 client_id 打点（供 llm/client.py 等无
        client_id 参数的深层调用点使用）。

        client_id 来源：server.services.voice_context 的 contextvar（audio.py
        的 _run_pipeline 已 set）。非语音路径（如文本聊天）读到默认 "default"，
        事件记入 "default" 键（不影响 per-client 轮次统计的可读性）。
        """
        try:
            from server.services.voice_context import get_active_client_id

            client_id = get_active_client_id()
        except Exception:  # noqa: BLE001 —— contextvar 不可用时降级
            client_id = "default"
        self.record(client_id, event, ts=ts)

    def _record_impl(
        self,
        client_id: str,
        event: Union[VoiceLatencyEvent, str],
        ts: Optional[float],
    ) -> None:
        ev = VoiceLatencyEvent(event)  # 非法事件名抛 ValueError → record 吞掉
        now = self._clock()
        if ts is None:
            ts = now

        with self._lock:
            # 懒清扫：先作废超时轮次，再处理本事件
            self._sweep_timeouts_locked(now)

            turn = self._active.get(client_id)

            if ev is VoiceLatencyEvent.SPEECH_END:
                if turn is not None and VoiceLatencyEvent.SPEECH_END in turn.events:
                    # 上一轮未等来 turn_done 即迎来新一轮 speech_end：
                    # 旧轮作废（未完成不结算），开新轮
                    del self._active[client_id]
                    turn = None
                if turn is None:
                    turn = _ActiveTurn(client_id=client_id)
                    self._active[client_id] = turn
                turn.events.setdefault(ev, ts)
                turn.last_event_ts = ts
                return

            # 非 speech_end 事件：无轮则隐式开轮（承接双流式"先于 speech_end
            # 到达"的 llm/tts 事件），speech_end 随后并入同一轮
            if turn is None:
                turn = _ActiveTurn(client_id=client_id)
                self._active[client_id] = turn

            if ev in _LAST_WINS_EVENTS:
                turn.events[ev] = ts  # 最后一次覆盖（如中段 final）
            else:
                turn.events.setdefault(ev, ts)  # 首次生效
            turn.last_event_ts = ts

            if ev is VoiceLatencyEvent.TURN_DONE:
                self._settle_turn_locked(client_id, turn)

    # ------------------------------------------------------------------
    # 结算与清扫
    # ------------------------------------------------------------------
    def _settle_turn_locked(self, client_id: str, turn: _ActiveTurn) -> None:
        """结算轮次：计算段延迟入缓冲，并从活跃表移除。

        只有至少能算出一段延迟的轮才入缓冲（完全无配对端点的轮没有统计价值，
        直接丢弃），避免空轮污染样本。
        """
        del self._active[client_id]
        events = turn.events
        segments: Dict[str, Optional[float]] = {}
        for name, (start_ev, end_ev) in _SEGMENT_DEFS.items():
            start_ts = events.get(start_ev)
            end_ts = events.get(end_ev)
            if start_ts is None or end_ts is None:
                segments[name] = None
            else:
                # 负序（如双流式 prefill 使 tts_first_chunk 先于 speech_end）
                # 按 0 记录：表示该段在参考点之前已完成
                segments[name] = round(max(0.0, (end_ts - start_ts) * 1000.0), 2)

        if all(v is None for v in segments.values()):
            return

        self._buffer.append(TurnRecord(
            client_id=client_id,
            settled_at=self._clock(),
            segments=segments,
            events={ev.value: ts for ev, ts in events.items()},
        ))

    def _sweep_timeouts_locked(self, now: float) -> None:
        """作废超时轮次（超过 turn_timeout_s 无事件进展的轮直接丢弃，不入缓冲）。"""
        expired = [
            cid for cid, t in self._active.items()
            if (now - t.last_event_ts) > self._turn_timeout_s
        ]
        for cid in expired:
            del self._active[cid]

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------
    def summary(self) -> Dict[str, Dict[str, Optional[float]]]:
        """聚合各段延迟：{段名: {p50, p95, max, count}}。无样本时段值为 None、count=0。"""
        try:
            with self._lock:
                self._sweep_timeouts_locked(self._clock())
                result: Dict[str, Dict[str, Optional[float]]] = {}
                for name in _SEGMENT_DEFS:
                    values = sorted(
                        rec.segments[name]
                        for rec in self._buffer
                        if rec.segments[name] is not None
                    )
                    result[name] = {
                        "p50": _percentile(values, 50),
                        "p95": _percentile(values, 95),
                        "max": round(max(values), 2) if values else None,
                        "count": len(values),
                    }
                return result
        except Exception:  # noqa: BLE001 —— 查询失败不影响调用方
            return {
                name: {"p50": None, "p95": None, "max": None, "count": 0}
                for name in _SEGMENT_DEFS
            }

    def recent(self, n: int = 20) -> List[dict]:
        """最近 n 轮已结算明细（时间升序，含 client_id / 时间戳 / 各段 ms）。"""
        try:
            with self._lock:
                if n <= 0:
                    return []
                records = list(self._buffer)[-n:]
                return [rec.to_dict() for rec in records]
        except Exception:  # noqa: BLE001
            return []

    def buffer_size(self) -> int:
        """当前缓冲内已结算轮次样本数。"""
        try:
            with self._lock:
                return len(self._buffer)
        except Exception:  # noqa: BLE001
            return 0

    @property
    def active_turn_count(self) -> int:
        """当前进行中（未结算）轮次数——测试与运维观测用。"""
        try:
            with self._lock:
                return len(self._active)
        except Exception:  # noqa: BLE001
            return 0


# ----------------------------------------------------------------------
# 模块级单例
# ----------------------------------------------------------------------
_voice_latency_tracker: Optional[VoiceLatencyTracker] = None
_voice_latency_tracker_lock = threading.Lock()


def get_voice_latency_tracker() -> VoiceLatencyTracker:
    """获取语音链路延迟采集器单例（惰性初始化，进程内共享）。"""
    global _voice_latency_tracker
    if _voice_latency_tracker is None:
        with _voice_latency_tracker_lock:
            if _voice_latency_tracker is None:
                _voice_latency_tracker = VoiceLatencyTracker()
    return _voice_latency_tracker
