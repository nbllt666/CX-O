"""CX-O-Autonomy 安全层——ContentGate 内容闸门。

对外输出进入发布通道前做内容安全检查，采取 fail-closed（异常即拒绝）策略：
- 若注入防火墙对象，调用其 filter_message(content, user_id, username)
  得到 FilterResult（allowed/reason），allowed=False 则拒绝；
- 可选人设一致性轻校验 persona_check(content) -> bool，支持同步或异步回调；
- 未注入防火墙时，仅做基础长度/空内容检查（此时基础检查是唯一防线）；
- enabled=False 时闸门关闭，直接放行（允许绕过）。

返回结构：{"allowed": bool, "reason": str, "checks": {...}}
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional

# 未注入防火墙时的基础内容长度上限（字符数）
MAX_CONTENT_LENGTH = 10000


class ContentGate:
    """内容闸门：防火墙 + 人设校验 + 基础检查，fail-closed 拒绝。"""

    def __init__(
        self,
        firewall: Optional[object] = None,
        persona_check: Optional[Callable[..., Any]] = None,
        enabled: bool = True,
    ) -> None:
        # 防火墙对象需暴露 filter_message(content, user_id, username) 返回 FilterResult
        self.firewall = firewall
        # 人设校验回调：persona_check(content) -> bool，可同步或异步
        self.persona_check = persona_check
        self.enabled = enabled

    def _basic_check(self, content: str) -> Optional[str]:
        """基础检查：空内容/超长内容命中时返回 reason，否则 None。"""
        if not content or not content.strip():
            return "empty_content"
        if len(content) > MAX_CONTENT_LENGTH:
            return "content_too_long"
        return None

    async def check(
        self,
        content: str,
        user_id: str = "autonomy",
        username: str = "autonomy",
    ) -> Dict[str, Any]:
        """执行内容安全检查，返回 {"allowed": bool, "reason": str, "checks": {...}}。"""
        checks: Dict[str, Any] = {"enabled": self.enabled}

        # 闸门关闭：直接放行
        if not self.enabled:
            return {"allowed": True, "reason": "gate_disabled", "checks": checks}

        # 1) 防火墙（注入时）：allowed=False 则拒绝
        if self.firewall is not None:
            filter_method = getattr(self.firewall, "filter_message", None)
            if filter_method is None:
                return {
                    "allowed": False,
                    "reason": "firewall_missing_filter_message",
                    "checks": checks,
                }
            try:
                result = filter_method(content, user_id, username)
                checks["firewall"] = {
                    "applied": True,
                    "allowed": bool(result.allowed),
                    "reason": str(getattr(result, "reason", "")),
                }
                if not result.allowed:
                    reason = getattr(result, "reason", "") or "content_rejected"
                    return {"allowed": False, "reason": reason, "checks": checks}
            except Exception as exc:  # fail-closed：防火墙异常视为拒绝
                checks["firewall"] = {"applied": True, "error": str(exc)}
                return {"allowed": False, "reason": "firewall_error", "checks": checks}
        else:
            # 2) 未注入防火墙：仅做基础长度/空内容检查
            basic = self._basic_check(content)
            checks["basic"] = {
                "applied": True,
                "empty": basic == "empty_content",
                "too_long": basic == "content_too_long",
            }
            if basic is not None:
                return {"allowed": False, "reason": basic, "checks": checks}

        # 3) 人设一致性校验（可选，同步/异步均可）
        if self.persona_check is not None:
            try:
                if inspect.iscoroutinefunction(self.persona_check):
                    ok = await self.persona_check(content)
                else:
                    ok = self.persona_check(content)
                checks["persona"] = {"applied": True, "allowed": bool(ok)}
                if not ok:
                    return {"allowed": False, "reason": "persona_mismatch", "checks": checks}
            except Exception as exc:  # fail-closed：校验异常视为拒绝
                checks["persona"] = {"applied": True, "error": str(exc)}
                return {"allowed": False, "reason": "persona_error", "checks": checks}

        return {"allowed": True, "reason": "ok", "checks": checks}
