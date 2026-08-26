"""模块四 · InterruptCoordinator —— 多向打断协调。

一对一只有"用户↔AI"双向打断；多方会议是"用户↔多 AI"+"AI↔AI"的多向打断，需优先级仲裁。

设计基准：《CX-O 多 Agent 语音会议协调器》§7。

优先级金字塔：
        用户说话（最高优先级）
       /          \
  被点名 Agent    正在说话的 Agent
     /                \
  想插话的 Agent（需仲裁）
"""
from __future__ import annotations

import inspect
import logging
from typing import Optional, Set

from server.core.meeting.models import AgentMember

logger = logging.getLogger(__name__)


class InterruptCoordinator:
    """多方打断协调器。

    Args:
        agent_interrupt_enabled: 是否允许 agent 打断 agent（默认关闭，进阶）。
        strong_reasons: 判定为"强理由"的打断原因集合（命中才允许打断）。
    """

    # 默认强理由：纠正错误 / 紧急 / 事实错误等（仅强理由才允许 agent 打断 agent）
    STRONG_REASONS = {"correction", "emergency", "fact_error", "place"}

    def __init__(
        self,
        agent_interrupt_enabled: bool = False,
        strong_reasons: Optional[Set[str]] = None,
    ):
        self.enabled = bool(agent_interrupt_enabled)
        self.strong_reasons = set(strong_reasons or self.STRONG_REASONS)

    async def on_user_speech(self, room) -> Optional[str]:
        """用户开口：最高优先级，强制收回令牌并让所有 agent 静音。

        Returns:
            被收回令牌的原持有者；无则 None。
        """
        # 先打断所有 agent（置 interrupted 标记）
        for agent in room.agents:
            if not await self._interrupt_agent(agent):
                logger.warning("用户打断：agent %s 强制静音失败", agent.agent_id)
        # 强制收回令牌（触发各 session 停 TTS）
        revoked = await room.token.revoke()
        return revoked

    async def on_agent_interrupt(
        self,
        room,
        from_agent_id: str,
        to_agent_id: str,
        reason: str = "",
    ) -> bool:
        """仲裁 agent 打断 agent：仅强理由才允许。

        Returns:
            True 表示打断被允许（令牌已转给 from）；False 表示被拒（进队列/继续等）。
        """
        if not self.enabled:
            logger.info("agent 互打断已关闭，拒绝 %s 打断 %s", from_agent_id, to_agent_id)
            return False
        if not self._is_strong_reason(reason):
            logger.info("理由「%s」非强理由，拒绝 %s 打断 %s", reason, from_agent_id, to_agent_id)
            return False

        # 强理由：先打断正在发言者，令牌转给打断者
        for agent in room.agents:
            if not await self._interrupt_agent(agent):
                logger.warning("强理由打断：agent %s 静音失败", agent.agent_id)
        # 强制收回当前持牌者
        await room.token.revoke()
        granted = await room.token.acquire(from_agent_id)
        if not granted:
            logger.warning(
                "强理由打断令牌获取失败：%s 未能取得令牌，打断 %s 被拒",
                from_agent_id, to_agent_id,
            )
            return False
        logger.info("强理由打断已放行：%s 打断 %s（granted=%s）", from_agent_id, to_agent_id, granted)
        return True

    # ---------------------------------------------------------------- 工具
    def _is_strong_reason(self, reason: str) -> bool:
        """判定理由是否为强理由（大小写不敏感）。"""
        r = (reason or "").strip().lower()
        if not r:
            return False
        return r in self.strong_reasons or any(k in r for k in self.strong_reasons)

    async def _interrupt_agent(self, agent: AgentMember) -> bool:
        """让单个 agent 停止 TTS（复用其 session 的打断逻辑）。

        会话不携带打断能力时仅置 interrupted 标记（降级，视为成功）。

        Returns:
            True 表示打断已下发/移除能力；False 表示打断失败。
            失败不再静默吞异常，向上反馈供调用方判知（保证用户强制静音优先级）。
        """
        agent.interrupted = True
        session = getattr(agent, "session", None)
        interrupt = getattr(session, "_interrupt_pipeline", None)
        if interrupt is None:
            return True
        try:
            if inspect.iscoroutinefunction(interrupt):
                await interrupt()
            return True
        except Exception as e:  # noqa: BLE001 打断失败需向上反馈，不静默吞异常
            logger.warning("打断 agent %s 失败: %s", agent.agent_id, e)
            return False