"""CX-O-Dream 自动清除任务（server/autonomy/dream/purge.py）。

DreamPurgeJob.run(agent_id) 清除（红线 R4，全部软删 + 审计）：
    ① 超 config.dream_ttl_hours 且未确认（consolidation_state in pending/surfaced）的梦境
    ② importance_score < config.purge_threshold 的梦境
    ③ dream_buffer 中已过期的候选（buffer.purge_expired 清理缓冲行）

只动 type='dream'：查询经 _DreamMixin.list_dreams（type='dream' 过滤），软删经
_DreamMixin.reject_dream（is_deleted=TRUE，内部按 type='dream' 限定并写 audit，
details.reason 标注清除原因）。**绝不误伤其他记忆**。唤醒窗口 + 每 6 小时兜底
定时触发（由 DreamEngine 编排）。

对应契约: public/interface_stub/dream.pyi（DreamPurgeJob.run 签名）
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from server.autonomy.dream.buffer import DreamBuffer
from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.engine import push_dream_event
from server.core.logging_config import get_contextual_logger
from server.protocol.actions import DreamActions

logger = get_contextual_logger(__name__)

# 清除原因标签（写入 reject_dream 审计 details.reason）
_REASON_TTL = "purged_ttl_expired"
_REASON_LOW_IMPORTANCE = "purged_low_importance"

# list_dreams 查询上限（默认 50 可能漏清大量梦境，此处放宽）
_LIST_LIMIT = 1000


def _parse_created_at(value) -> Optional[datetime]:
    """解析 memories.created_at（ISO 字符串）为 datetime；非法返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


class DreamPurgeJob:
    """梦境自动清除任务。

    Args:
        memory_manager: 记忆管理器（MemoryManager，含 _DreamMixin）
        buffer: 梦境候选缓冲（DreamBuffer）
        config: DreamConfig；None 时使用全默认
        ws_manager: 可选 WebSocket 管理器；None 时清除后不推送（静默）
    """

    def __init__(
        self,
        memory_manager,
        buffer: DreamBuffer,
        config: Optional[DreamConfig] = None,
        ws_manager: Optional[Any] = None,
    ):
        self.memory_manager = memory_manager
        self.buffer = buffer
        self.config = config or DreamConfig()
        self._ws_manager = ws_manager

    # -------------------------------------------------------------- 执行
    async def run(self, agent_id: str = "default") -> Dict:
        """执行一轮自动清除，返回被清除数量统计。

        先按 TTL 过期 + 未确认清理，再按低重要性清理（第二次 list_dreams
        已排除首次软删的梦境，不会重复计数）；最后清理缓冲过期候选。

        Args:
            agent_id: Agent ID

        Returns:
            {"purged_memories": int, "purged_buffer": int}
        """
        now = datetime.now()
        ttl = timedelta(hours=self.config.dream_ttl_hours)
        purged_memories = 0

        # ① 超 TTL 且未确认（pending/surfaced）
        for mem in self.memory_manager.list_dreams(agent_id=agent_id, limit=_LIST_LIMIT):
            state = (mem.get("metadata") or {}).get("consolidation_state")
            if state not in ("pending", "surfaced"):
                continue
            created = _parse_created_at(mem.get("created_at"))
            if created is not None and now - created > ttl:
                if self.memory_manager.reject_dream(mem["id"], reason=_REASON_TTL):
                    purged_memories += 1

        # ② importance_score < purge_threshold
        threshold = self.config.purge_threshold
        for mem in self.memory_manager.list_dreams(agent_id=agent_id, limit=_LIST_LIMIT):
            score = mem.get("importance_score")
            if score is not None and score < threshold:
                if self.memory_manager.reject_dream(mem["id"], reason=_REASON_LOW_IMPORTANCE):
                    purged_memories += 1

        # ③ 缓冲过期候选
        purged_buffer = self.buffer.purge_expired()

        logger.info(
            "梦境自动清除完成: agent=%s, purged_memories=%s, purged_buffer=%s",
            agent_id,
            purged_memories,
            purged_buffer,
        )
        # 清除完成后推送 dream.purged（S→C；ws_manager 为 None 时静默，不阻断）
        await push_dream_event(
            self._ws_manager,
            DreamActions.PURGED,
            {
                "agent_id": agent_id,
                "purged_memories": purged_memories,
                "purged_buffer": purged_buffer,
            },
        )
        return {"purged_memories": purged_memories, "purged_buffer": purged_buffer}
