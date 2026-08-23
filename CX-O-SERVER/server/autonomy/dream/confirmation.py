"""休眠前 LLM 确认仲裁器（server/autonomy/dream/confirmation.py）。

在 SleepSensor 判定需要入睡（PENDING_CONFIRMATION / ENTERING_SLEEP）但开启休眠前
确认开关时，调用 LLM 对近期上下文做二次仲裁：判定 should_sleep。任何异常 / 超时 /
解析失败均安全降级（fail-open 返回 True，与现有多路传感器确认口径一致——宁可误入睡
也不阻塞用户请求，不把失败风险转嫁给聊天主流程）。

- enabled=False → approve_sleep 直接返回 True（不调用 LLM）
- 冷却期（config.cooldown_seconds）内不重复打扰 → approve_sleep 返回 True
- 本模块纯声明式：不做任何文件 IO，禁止相对路径访问
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from server.autonomy.dream.config import SleepConfirmationConfig

logger = logging.getLogger(__name__)

# 判定为"可以入睡"的文本信号口径（大小写归一后匹配）
_TRUE_TOKENS = frozenset(
    {"true", "yes", "y", "1", "allowed", "approve", "approved", "confirm", "是", "同意", "允许", "确认"}
)
_FALSE_TOKENS = frozenset(
    {"false", "no", "n", "0", "denied", "deny", "reject", "rejected", "拒绝", "否", "不同意", "不允许"}
)
# 结构化结果中可识别的"入睡意图"键名（按优先级依次探测）
_DECISION_KEYS = ("should_sleep", "approve", "approved", "confirm", "允许休眠", "decision")


class SleepConfirmationArbiter:
    """休眠前确认仲裁器。

    Args:
        llm_client: 可选的 LLM 客户端。优先识别 async ``chat(messages=..., stream=False)``
            返回带 ``.content`` 的对象（对齐生成器调用口径）；其次兼容
            ``await llm_client(prompt)`` 直接返回文本 / 结构化值的可调用对象。
            为 None 时 approve_sleep 直接 fail-open 返回 True（不调用 LLM）。
        recent_context_fn: 可选的近期上下文读取回调 ``() -> str``，追加进提示词。
        config: SleepConfirmationConfig（默认全新实例，enabled=True、无冷却）。
        now_fn: 当前时间提供函数（默认 datetime.now，便于测试注入固定时钟）。
        timeout_sec: 单次 LLM 判定的超时秒数（默认取 config.timeout_sec）。
    """

    def __init__(
        self,
        llm_client: Optional[Any] = None,
        recent_context_fn: Optional[Callable[[], str]] = None,
        config: Optional[SleepConfirmationConfig] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
        timeout_sec: Optional[float] = None,
    ):
        self._llm_client = llm_client
        self._recent_context_fn = recent_context_fn
        self._config = config or SleepConfirmationConfig()
        self._now_fn = now_fn or datetime.now
        self._timeout_sec = (
            self._config.timeout_sec if timeout_sec is None else timeout_sec
        )
        self._last_confirmed_at: Optional[datetime] = None

    # -------------------------------------------------------------- 冷却判定
    def should_skip(self, now: datetime, last_confirmed_at: Optional[datetime]) -> bool:
        """冷却期判断：距今未超过 cooldown_seconds 时返回 True（不重复打扰）。

        last_confirmed_at 为 None（从未确认）→ 返回 False（立即放行仲裁）。
        """
        if last_confirmed_at is None:
            return False
        elapsed = (now - last_confirmed_at).total_seconds()
        return elapsed < max(0.0, float(self._config.cooldown_seconds))

    # -------------------------------------------------------------- 仲裁入口
    async def approve_sleep(self, context_text: str) -> bool:
        """对休眠前的用户上下文做 LLM 二次确认，返回是否允许入睡。

        - config.enabled=False → 直接 True（不调用 LLM）
        - 冷却期内 → 直接 True（不重复打扰/不重复调用 LLM）
        - LLM 缺席 / 超时 / 异常 / 解析失败 → fail-open True（异常隔离，绝不抛出）
        - LLM 判定明确允许 → True；明确拒绝 → False
        """
        if not self._config.enabled:
            return True
        now = self._now_fn()
        if self.should_skip(now, self._last_confirmed_at):
            return True

        prompt = self._build_prompt(context_text)
        decision: Optional[bool] = None
        try:
            decision = await self._ask_llm(prompt)
        except Exception as e:  # 超时 / LLM 异常 → fail-open，隔离不抛出
            logger.warning("休眠确认仲裁失败，fail-open 放行（不影响主流程）: %s", e)

        if decision is None:
            logger.debug("休眠确认仲裁无有效判定，fail-open 放行")
            return True

        # 记录有效判定时刻，供后续冷却不重复打扰
        self._last_confirmed_at = now
        return decision

    # -------------------------------------------------------------- 引擎兼容入口
    async def confirm(self, snapshot: Optional[Dict[str, Any]] = None) -> bool:
        """入睡确认闸门兼容入口（对齐 DreamEngine._sleep_confirmation_gate 口径）。

        引擎当 arbiter 暴露 ``confirm``/``should_confirm``/``is_confirmed`` 之一时以其
        调用；这里把引擎传入的 ``snapshot`` 归一为轻量上下文串后复用 ``approve_sleep``
        完成同源 LLM 仲裁，保证引擎侧接入真实仲裁器时零重复实现。
        """
        context_text = self._snapshot_to_context(snapshot)
        return await self.approve_sleep(context_text)

    @staticmethod
    def _snapshot_to_context(snapshot: Optional[Dict[str, Any]]) -> str:
        """把 SleepSensor 快照归一为可读上下文串（缺失时返回空串）。"""
        if not isinstance(snapshot, dict):
            return ""
        lines: list[str] = []
        state = snapshot.get("state")
        if state:
            lines.append(f"当前睡眠融合状态: {state}")
        confidence = snapshot.get("confidence")
        if confidence is not None:
            lines.append(f"置信度: {confidence}")
        return "\n".join(lines)

    # -------------------------------------------------------------- 内部
    async def _ask_llm(self, prompt: str) -> Optional[bool]:
        """调用 LLM 获取判定原始结果，返回解析后的布尔；无有效判定返回 None。"""
        client = self._llm_client
        if client is None:
            return None
        text = await self._invoke(client, prompt)
        return self._resolve_decision(text)

    async def _invoke(self, client: Any, prompt: str) -> Any:
        """兼容两种客户端形态调用，统一返回原始文本 / 结构化结果。"""
        if hasattr(client, "chat"):
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一个休眠意图确认助手。请结合用户上下文，仅判断用户"
                        "是否因疲惫/想睡而应该进入休眠。原则：宁可保守，不因误判打扰。"
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            resp = client.chat(messages=messages, stream=False)
            if inspect.isawaitable(resp):
                resp = await resp
            # 对齐生成器口径：读带 .content 的对象；兼容 dict
            if isinstance(resp, dict):
                return resp.get("content") or resp
            return getattr(resp, "content", None) or ""

        # 兼容简单可调用对象：await llm_client(prompt) 直接返回文本/结构化值
        result = client(prompt)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _build_prompt(self, context_text: str) -> str:
        """组装判定提示词：模板 + 当前上下文 + 可选近期上下文。"""
        parts: list[str] = []
        template = (self._config.prompt_template or "").strip()
        if template:
            parts.append(template)
        recent = self._load_recent_context()
        if context_text and context_text.strip():
            parts.append(f"【当前用户上下文】\n{context_text.strip()}")
        if recent:
            parts.append(f"【近期上下文】\n{recent.strip()}")
        parts.append("请判断用户是否应进入休眠。仅回答：是 / 否。")
        return "\n".join(parts)

    def _load_recent_context(self) -> str:
        """读取近期上下文回调（异常隔离，缺失返回空串）。"""
        if self._recent_context_fn is None:
            return ""
        try:
            return str(self._recent_context_fn() or "")
        except Exception as e:
            logger.debug("近期上下文读取失败（忽略）: %s", e)
            return ""

    # -------------------------------------------------------------- 判定解析
    @staticmethod
    def _resolve_decision(raw: Any) -> Optional[bool]:
        """把 LLM 的文本 / 结构化返回归一为布尔判定；无法识别返回 None。"""
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw) if raw in (0, 1) else None
        if isinstance(raw, dict):
            for key in _DECISION_KEYS:
                if key in raw and raw[key] is not None:
                    return SleepConfirmationArbiter._resolve_decision(raw[key])
            return None
        text = str(raw).strip()
        if not text:
            return None
        # 内嵌 JSON 对象字符串 → 递归解析
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return SleepConfirmationArbiter._resolve_decision(parsed)
            except (ValueError, TypeError):
                pass
        # "should_sleep: true / = false" 之类的键值对
        m = re.search(r"should_sleep[\"' ]*[:=][\"' ]*([\w\u4e00-\u9fff]+)", text, re.IGNORECASE)
        if m:
            token = m.group(1).strip().lower()
            if token in _TRUE_TOKENS:
                return True
            if token in _FALSE_TOKENS:
                return False
        low = text.lower()
        if low in _TRUE_TOKENS:
            return True
        if low in _FALSE_TOKENS:
            return False
        return None