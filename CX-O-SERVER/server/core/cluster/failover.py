"""接管管理器：candidate → epoch+1 → 仲裁 → 复活灵魂（继承遗产）→ active。

- maybe_takeover(dead_node_id) -> dict
  - 本节点转 candidate，epoch+1，经 consensus.can_takeover 仲裁
  - 通过后 adopt_inheritance（保持自身 identity，仅记录 inherited_from）
  - 晋升 active，广播 failover_started / failover_completed 事件
  - 任一步仲裁失败返回 took_over=False + error_code，并恢复 standby
- adopt_inheritance(from_node_id)：本节点保持自身身份，记录继承遗产来源。
"""
from __future__ import annotations

import time

from ._common import ClusterError


def _iso(t=None) -> str:
    from datetime import datetime

    t = t or time.time()
    return datetime.fromtimestamp(t).astimezone().isoformat()


class FailoverManager:
    def __init__(
        self,
        config=None,
        consensus=None,
        node_id: str = "",
        transport=None,
        state_source: callable = None,
        event_source: callable = None,
        current_epoch: int = 0,
    ):
        self._config = config
        self._consensus = consensus
        self._node_id = node_id
        self._transport = transport
        self._state_source = state_source  # fn(dead_node_id) -> (candidate_version, min_version)
        self._event_source = event_source  # fn(topic, data)
        self._epoch = current_epoch
        self._role = getattr(config, "role", "standby") if config else "standby"
        self.inherited_from: str | None = None

    # ---- 依赖注入 ----
    def set_state_source(self, fn):
        self._state_source = fn

    def set_event_source(self, fn):
        self._event_source = fn

    def set_consensus(self, c):
        self._consensus = c

    def set_transport(self, t):
        self._transport = t

    def set_role(self, role):
        self._role = role

    def set_epoch(self, epoch):
        self._epoch = epoch

    @property
    def role(self) -> str:
        return self._role

    @property
    def epoch(self) -> int:
        return self._epoch

    def _emit(self, topic: str, data: dict):
        if self._event_source:
            self._event_source(topic, data)

    async def maybe_takeover(self, dead_node_id: str) -> dict:
        new_epoch = self._epoch + 1
        self._role = "candidate"

        candidate_version, min_version = 0, 0
        if self._state_source:
            try:
                candidate_version, min_version = self._state_source(dead_node_id)
            except Exception:  # noqa: BLE001 - 兜底为 0/0（min=0 不触发脏接管）
                candidate_version, min_version = 0, 0

        try:
            self._consensus.can_takeover(
                from_node_id=dead_node_id,
                candidate_state_version=candidate_version,
                min_version=min_version,
                epoch=new_epoch,
            )
        except ClusterError as e:
            # 仲裁失败：恢复 standby。epoch 保持不变（仅在仲裁成功后才递增），
            # 避免失败尝试导致 epoch 不可逆地被消耗。
            self._role = (getattr(self._config, "role", "standby") or "standby") if self._config else "standby"
            self._emit("failover_started", {"from_node": dead_node_id, "decision": "rejected", "reason": e.error_code})
            return {
                "took_over": False,
                "role": self._role,
                "from_node_id": dead_node_id,
                "epoch": self._epoch,
                "error_code": e.error_code,
                "message": e.message,
            }

        # 仲裁成功后才递增 epoch，保证失败尝试不消耗纪元
        self._epoch = new_epoch
        self._emit("failover_started", {"from_node": dead_node_id, "decision": "proceeding"})
        await self.adopt_inheritance(dead_node_id)
        self._role = "active"
        self._emit("failover_completed", {
            "from_node": dead_node_id,
            "to_node": self._node_id,
            "inherited_from": dead_node_id,
            "epoch": new_epoch,
        })
        return {
            "took_over": True,
            "role": "active",
            "from_node_id": dead_node_id,
            "epoch": new_epoch,
            "inherited_from": dead_node_id,
            "node_id": self._node_id,
        }

    async def adopt_inheritance(self, from_node_id: str) -> None:
        """复活灵魂（B 继承 A 记忆为遗产）。保持本节点自身 identity，仅记录来源。"""
        self.inherited_from = from_node_id
        return None
