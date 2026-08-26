"""直播弹幕隐式反馈追踪器。

在 AI 回复后的一段窗口内，用 EmotionAnalyzer 规则引擎分析弹幕情感极性，
检测「情绪爆发」（正向/负向弹幕达到阈值），判定 chosen/rejected 并产出
``FeedbackIn``（source=live_danmaku），异步推到 CXO-Tuner。

设计要点（对齐 CX-O 核心零影响原则）：
  - 无 AI 回复记录时不触发；
  - 同 prompt/回复不重复上报（去重）；
  - auto_push=False（默认）或 Tuner 不可达时静默降级，绝不抛异常破坏 danmaku 主路径。

使用方式（增量接入，不改变原有弹幕处理路径）：
    tracker = get_live_feedback_tracker()
    tracker.record_ai_response(text, ts)     # AI 回复产生时记录
    await tracker.on_danmaku(content, ...)   # 弹幕过滤通过后喂入（异步，可 fire-and-forget）
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, List, Optional, Sequence

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 无历史可对比时的非空中性对比占位模板（保证 response_chosen/rejected 满足 minLength:1）。
_FALLBACK_ALTERNATIVE = "（简短重述用户问题并给出一个稳妥、中性的回答。）"

# 模块级可选：默认情感分析器（惰性绑定，避免 import 时触发额外副作用）
_emotion_analyzer = None


def _get_emotion_analyzer():
    """惰性获取全局 EmotionAnalyzer（规则引擎），供 tracker 分析弹幕极性。"""
    global _emotion_analyzer
    if _emotion_analyzer is None:
        from server.core.memory.emotion import EmotionAnalyzer

        _emotion_analyzer = EmotionAnalyzer()
    return _emotion_analyzer


def _get_evolution_config():
    """惰性读取 evolution 配置节，供 tracker 判断 auto_push 等开关。"""
    from server.config import get_config

    return get_config().evolution


_tuner_client = None


def _get_tuner_client():
    """惰性构建/复用 TunerClient（host 变更时重建），用于默认推送实现。"""
    global _tuner_client
    from server.api.routers.tuner import TunerClient

    cfg = _get_evolution_config()
    if _tuner_client is None or _tuner_client.base_url != cfg.host:
        _tuner_client = TunerClient(base_url=cfg.host, timeout=cfg.timeout)
    return _tuner_client


async def _default_push_feedback(payload: dict) -> Optional[Any]:
    """默认推送实现：直接调用 CXO-Tuner 客户端（不可达时内部静默降级到 None）。"""
    return await _get_tuner_client().submit_feedback(payload)


class LiveFeedbackTracker:
    """维护「上一轮 AI 回复」记录与弹幕情感窗口，产出并推送隐式反馈。"""

    def __init__(
        self,
        emotion_analyzer=None,
        push_func: Optional[Callable[[dict], Awaitable[None]]] = None,
        window_seconds: float = 10.0,
        burst_threshold: int = 3,
        intensity_threshold: float = 0.5,
        get_config=None,
    ):
        self._emotion = emotion_analyzer
        self._push_func = push_func
        self._window_seconds = float(window_seconds)
        self._burst_threshold = int(burst_threshold)
        self._intensity_threshold = float(intensity_threshold)
        self._get_config = get_config or _get_evolution_config

        # 最近一轮 AI 回复：{"text", "prompt", "ts"}
        self._last_response: Optional[dict] = None
        # 历史 AI 回复（供对比样本回退），最多保留近 20 轮
        self._response_history: deque = deque(maxlen=20)
        # 当前窗口内的弹幕情感累计
        self._window: List[dict] = []
        # 已上报指纹（prompt+response md5），避免同回复重复上报。
        # 有界 deque（纯成员判定 + append 追加即可）仅保留最近指纹，防止长期运行无界增长。
        self._reported_fingerprints: deque = deque(maxlen=2000)

    # ------------------------------------------------------------------ #
    # 记录 / 反馈入口
    # ------------------------------------------------------------------ #
    def record_ai_response(self, text: str, ts: Optional[float] = None, prompt: str = "") -> None:
        """记录一轮 AI 回复，并清空上一轮窗口累积。

        params:
            text: 助手回复正文
            ts: 记录时间戳（秒），默认取当前时间
            prompt: 触发该回复的用户提示（供 FeedbackIn.prompt 使用）
        """
        # 本轮覆盖前，将上一轮回复沉淀进历史（供后续对比样本回退）
        if self._last_response is not None:
            self._response_history.append(self._last_response)
        self._last_response = {
            "text": text or "",
            "prompt": prompt or "",
            "ts": ts if ts is not None else time.time(),
        }
        self._window = []

    async def on_danmaku(
        self,
        text: str,
        user_id: str = "",
        ts: Optional[float] = None,
        session_id: str = "",
    ) -> Optional[dict]:
        """处理一条过滤后放行的弹幕，检测情感爆发并在命中时推送反馈。

        params:
            text: 弹幕文本
            user_id: 弹幕用户 ID
            ts: 弹幕时间戳（秒），默认取当前时间
            session_id: 会话 ID，写入 FeedbackIn.session_id

        returns:
            命中并构造出的 feedback payload（dict），未命中或静默降级返回 None。
            任何异常被捕获，保证调用方（danmaku 主路径）零影响。
        """
        try:
            if self._last_response is None:
                return None

            if ts is None:
                ts = time.time()

            # 窗口过期（超出 AI 回复后 window_seconds）则忽略
            if ts - self._last_response["ts"] > self._window_seconds:
                return None

            result = await self._emotion.analyze(text)
            if (
                result.emotion_type not in ("positive", "negative")
                or result.intensity < self._intensity_threshold
            ):
                return None

            self._window.append(
                {
                    "emotion": result.emotion_type,
                    "intensity": result.intensity,
                    "ts": ts,
                    "keywords": result.keywords,
                }
            )

            fingerprint = self._fingerprint()
            if fingerprint in self._reported_fingerprints:
                return None

            decision = self._evaluate()
            if decision is None:
                return None

            payload = self._build_payload(decision, session_id=session_id)
            await self._safe_push(payload)
            self._reported_fingerprints.append(fingerprint)
            return payload
        except Exception as e:  # 静默降级：任何异常不向上抛
            logger.warning(f"live_feedback 弹幕反馈处理降级: {e}")
            return None

    # ------------------------------------------------------------------ #
    # 判定逻辑
    # ------------------------------------------------------------------ #
    def _active_window(self) -> List[dict]:
        """返回处于 AI 回复窗口内的弹幕情感记录。"""
        if self._last_response is None:
            return []
        window_key = self._last_response["ts"] + self._window_seconds
        return [d for d in self._window if d["ts"] <= window_key]

    def _evaluate(self) -> Optional[dict]:
        """判定是否发生情绪爆发及 chosen/rejected 方向。

        返回 {"sentiment": "positive"/"negative", "chosen": str, "rejected": str}
        或 None（未达爆发阈值）。
        """
        active = self._active_window()
        pos = sum(1 for d in active if d["emotion"] == "positive")
        neg = sum(1 for d in active if d["emotion"] == "negative")

        if pos >= self._burst_threshold or neg >= self._burst_threshold:
            response = self._last_response["text"] or ""
            alternative = self._alternative_text(exclude=response)

            if pos > neg:  # 正向占优 → chosen=当前回复
                return {"sentiment": "positive", "chosen": response or alternative, "rejected": alternative}
            # 负向占优（含 pos==neg）→ rejected=当前回复
            return {"sentiment": "negative", "chosen": alternative, "rejected": response or alternative}
        return None

    def _alternative_text(self, exclude: str = "") -> str:
        """返回非空对比样本，保证 minLength:1（绝不返回空串）。

        优先取历史中与 ``exclude`` 不同的非空 AI 回复；否则返回非空中性对比占位模板。
        若 ``exclude`` 也为空，则直接返回非空模板，保证 selected 一方恒非空。
        """
        exclude = (exclude or "").strip()
        for past in reversed(self._response_history):
            text = (past.get("text") or "").strip()
            if text and text != exclude:
                return text
        return _FALLBACK_ALTERNATIVE

    def _fingerprint(self) -> str:
        """构造去重指纹：prompt + response 的 md5。"""
        raw = f"{self._last_response['prompt']}|{self._last_response['text']}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def _build_payload(self, decision: dict, session_id: str = "") -> dict:
        """按 FeedbackIn 模型构造 payload（source=live_danmaku）。"""
        active = self._window
        keywords: List[str] = []
        for d in active:
            for kw in d.get("keywords", []):
                if kw not in keywords:
                    keywords.append(kw)
        pos = sum(1 for d in active if d["emotion"] == "positive")
        neg = sum(1 for d in active if d["emotion"] == "negative")

        quality_score = 1.0
        return {
            "prompt": self._last_response["prompt"],
            "response_chosen": decision["chosen"],
            "response_rejected": decision["rejected"],
            "source": "live_danmaku",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id or None,
            "quality_score": quality_score,
            "metadata": {
                "danmaku_sentiment": decision["sentiment"],
                "keywords": keywords[:20],
                "window_counts": {"positive": pos, "negative": neg},
            },
        }

    # ------------------------------------------------------------------ #
    # 推送（静默降级）
    # ------------------------------------------------------------------ #
    async def _safe_push(self, payload: dict) -> None:
        """按 auto_push 开关决定是否推送；推送失败静默降级不抛异常。"""
        try:
            cfg = self._get_config()
            # auto_push 未开启则不推送（默认关闭，避免改变既有行为）
            if not bool(getattr(cfg, "auto_push", False)):
                return
            push = self._push_func
            if push is None:
                return
            await push(payload)
        except Exception as e:
            logger.warning(f"live_feedback 推送降级: {e}")


# --------------------------------------------------------------------------- #
# 单例
# --------------------------------------------------------------------------- #
_tracker: Optional[LiveFeedbackTracker] = None


def get_live_feedback_tracker() -> LiveFeedbackTracker:
    """返回全局唯一的 LiveFeedbackTracker 单例。"""
    global _tracker
    if _tracker is None:
        _tracker = LiveFeedbackTracker(
            emotion_analyzer=_get_emotion_analyzer(),
            push_func=_default_push_feedback,
        )
    return _tracker