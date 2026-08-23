"""CX-O-Dream 梦境固化/清除（server/autonomy/dream/consolidator.py）。

三态处理（spec "DreamConsolidator 固化/清除"）：
- consolidate(buffer_id)：用户确认 → 经 _DreamMixin.write_dream_memory 写主库
  （type='dream'，consolidation_state='confirmed'、importance_score 提至
  confirmed_importance、is_ground_truth 保持 false）→ consolidate_dream 提级 →
  buffer.mark_decision('approved')。**固化 ≠ 变成事实**。
- reject(buffer_id)：用户否定 → buffer.mark_decision('rejected', reason)
  （保留 30 天审计由 buffer 处理），不写主库。
- surface(agent_id)：唤醒窗口按 surface_probability 概率 + max_surface_per_day
  每日次数上限决定是否主动提起，经 ws_sender 推送（None 时仅记日志）。

对应契约: public/interface_stub/dream.pyi（consolidate/reject/surface 签名）
"""

from __future__ import annotations

import inspect
import random
from datetime import date, datetime
from typing import Any, Callable, Dict, Optional

from server.autonomy.dream.buffer import DreamBuffer
from server.autonomy.dream.config import DreamConfig
from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class DreamConsolidator:
    """梦境候选固化 / 清除 / 主动提起。

    Args:
        buffer: 梦境候选缓冲（DreamBuffer）
        memory_manager: 记忆管理器（MemoryManager，含 _DreamMixin）
        config: DreamConfig；None 时使用全默认
        ws_sender: 可选推送回调（sync/async callable，接收完整 WS 消息 dict）；
            None 时 surface 仅记日志，照常计数
    """

    def __init__(
        self,
        buffer: DreamBuffer,
        memory_manager,
        config: Optional[DreamConfig] = None,
        ws_sender: Optional[Callable[..., Any]] = None,
    ):
        self.buffer = buffer
        self.memory_manager = memory_manager
        self.config = config or DreamConfig()
        self.ws_sender = ws_sender
        # surface 每日次数计数（跨日自动重置）
        self._surface_date: Optional[date] = None
        self._surface_count: int = 0

    # -------------------------------------------------------------- 固化（确认）
    def consolidate(self, buffer_id: int, agent_id: str = "default") -> Optional[int]:
        """固化一条梦境候选：写主库 + 提级 + 缓冲置 approved。

        候选不存在或已决策（rejected/approved）时返回 None（不重复固化）。
        固化的核心元数据（dream_session_id / source / lucidity / 关联素材）随
        write_dream_memory 落库；consolidation_state / confirmed_at / importance_score
        由 consolidate_dream 提级完成。

        Args:
            buffer_id: 缓冲候选 id
            agent_id: Agent ID

        Returns:
            新写入的梦境记忆 id；候选不存在或已决策返回 None。
        """
        candidate = self.buffer.get(buffer_id)
        if candidate is None:
            return None
        if candidate.get("decision") in ("rejected", "approved"):
            logger.info(
                "候选已决策，跳过固化: buffer_id=%s, decision=%s",
                buffer_id,
                candidate.get("decision"),
            )
            return None

        now_iso = datetime.now().isoformat()
        metadata = {
            "source": "dream_engine",
            "dream_session_id": candidate["dream_session_id"],
            "is_ground_truth": False,
            "lucidity_score": candidate.get("lucidity_score", 0.0),
            "associated_memories": candidate.get("associated_memories"),
            "associated_entities": candidate.get("associated_entities"),
            "emotion_shift": candidate.get("emotion_shift"),
            # write_dream_memory 强制 pending/confirmed_at=None，固化状态由
            # consolidate_dream 提级（consolidation_state -> confirmed）
            "consolidation_state": "confirmed",
            "confirmed_at": now_iso,
        }
        memory_id = self.memory_manager.write_dream_memory(
            content=candidate["candidate_content"],
            dream_session_id=candidate["dream_session_id"],
            metadata=metadata,
            agent_id=agent_id,
        )
        confirmed = self.memory_manager.consolidate_dream(
            memory_id, confirmed_importance=self.config.confirmed_importance
        )
        if not confirmed:
            logger.warning(
                "固化提级未生效（可能状态不符）: memory_id=%s, buffer_id=%s",
                memory_id,
                buffer_id,
            )
        self.buffer.mark_decision(buffer_id, "approved", reason="user_confirmed")
        logger.info(
            "梦境候选已固化: buffer_id=%s -> memory_id=%s, agent=%s",
            buffer_id,
            memory_id,
            agent_id,
        )
        return memory_id

    # -------------------------------------------------------------- 清除（否定）
    def reject(self, buffer_id: int, agent_id: str = "default", reason: str = "") -> bool:
        """否定一条梦境候选：缓冲置 rejected（保留 30 天审计），不写主库。

        Args:
            buffer_id: 缓冲候选 id
            agent_id: Agent ID
            reason: 否定原因（写入 decision_reason）

        Returns:
            是否命中并标记成功；候选不存在或已 rejected 返回 False。
        """
        candidate = self.buffer.get(buffer_id)
        if candidate is None:
            return False
        if candidate.get("decision") == "rejected":
            return False
        ok = self.buffer.mark_decision(buffer_id, "rejected", reason)
        if ok:
            logger.info(
                "梦境候选已否定: buffer_id=%s, agent=%s, reason=%s",
                buffer_id,
                agent_id,
                reason,
            )
        return ok

    # -------------------------------------------------------------- 主动提起
    async def surface(self, agent_id: str = "default") -> bool:
        """按概率与每日次数上限主动提起一条梦境候选。

        提起条件（全部满足才推送）：
            1. config.surface_on_wake 为真
            2. 当日提起次数未达 config.max_surface_per_day（跨日自动重置）
            3. random() < config.surface_probability（概率门）
            4. 缓冲存在待决策（pending）候选

        推送消息为 {"type": "dream.surface", "data": {...}}（对齐 spec WS 约定）。
        ws_sender 为 None 时仅记日志并照常计数；推送异常不抛错（记录后返回 False）。

        Args:
            agent_id: Agent ID

        Returns:
            是否成功提起并推送。
        """
        if not self.config.surface_on_wake:
            return False

        today = datetime.now().date()
        if self._surface_date != today:
            self._surface_date = today
            self._surface_count = 0
        if self._surface_count >= self.config.max_surface_per_day:
            logger.info("当日提起次数已达上限，跳过: agent=%s", agent_id)
            return False

        if random.random() >= self.config.surface_probability:
            logger.info("未命中提起概率，跳过: agent=%s", agent_id)
            return False

        candidates = self.buffer.list(agent_id=agent_id, decision="pending", limit=1)
        if not candidates:
            logger.info("无待决策梦境候选，跳过提起: agent=%s", agent_id)
            return False
        candidate = candidates[0]

        data: Dict[str, Any] = {
            "dream_session_id": candidate["dream_session_id"],
            "buffer_id": candidate["id"],
            "content": candidate["candidate_content"],
            "lucidity_score": candidate.get("lucidity_score", 0.0),
            "emotion_shift": candidate.get("emotion_shift"),
            "agent_id": agent_id,
        }
        message = {"type": "dream.surface", "data": data}

        if self.ws_sender is None:
            logger.info("梦境主动提起（无 ws_sender，仅记录）: %s", data)
            self._surface_count += 1
            return True

        try:
            result = self.ws_sender(message)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.error("梦境主动提起推送失败: %s", e, exc_info=True)
            return False

        self._surface_count += 1
        logger.info("梦境主动提起已推送: %s", data)
        return True
