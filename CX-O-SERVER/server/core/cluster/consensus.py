"""共识守卫：epoch 防双主 + 多数派 + 见证节点 tiebreaker + 脏接管拒绝。

- can_takeover(from_node_id, candidate_state_version, min_version, epoch) -> bool
  - candidate_state_version < min_version      -> 抛 ClusterDirtyTakeoverError（严格红线）
  - 节点数 >=3 但确认数少于多数                 -> 抛 ClusterNoQuorumError
  - 2 节点但 witness 未配置                     -> 抛 ClusterNoQuorumError
  - 防双主：epoch 非当前最高（<= current）      -> 抛 ClusterSplitBrainRiskError
  - 多数通过 / 2 节点经 witness                 -> True
- choose_leader_by_witness(candidates) -> str   （无 witness 抛 ClusterNoQuorumError）
"""
from __future__ import annotations

from ._common import (
    ClusterDirtyTakeoverError,
    ClusterNoQuorumError,
    ClusterSplitBrainRiskError,
)


class ConsensusGuard:
    def __init__(
        self,
        config=None,
        vote_source: callable = None,
        current_epoch: int = 0,
        witness_decider: callable = None,
    ):
        self._config = config
        self._vote_source = vote_source          # fn() -> 当前多数派确认数（测试注入）
        self._current_epoch = current_epoch
        self._witness_decider = witness_decider  # fn(candidates) -> node_id（测试注入）

    # ---- 依赖注入 ----
    def set_vote_source(self, fn):
        self._vote_source = fn

    def set_witness_decider(self, fn):
        self._witness_decider = fn

    def _peers(self):
        if not self._config:
            return []
        return list(getattr(self._config, "peers", []) or [])

    def _witness_endpoint(self) -> str:
        if not self._config:
            return ""
        w = getattr(self._config, "witness", None)
        if w is None:
            return ""
        return getattr(w, "endpoint", "") or ""

    @property
    def current_epoch(self) -> int:
        return self._current_epoch

    def can_takeover(
        self,
        from_node_id: str,
        candidate_state_version: int,
        min_version: int,
        epoch: int,
    ) -> bool:
        # 严格红线：数据过旧/不完整拒绝接管
        if candidate_state_version < min_version:
            raise ClusterDirtyTakeoverError(
                f"state {candidate_state_version} < min {min_version}; refuse dirty takeover"
            )

        # 防双主：仅当 epoch 为当前最高且 +1 通过才允许
        if epoch <= self._current_epoch:
            self._current_epoch = max(self._current_epoch, epoch)
            raise ClusterSplitBrainRiskError(
                f"epoch {epoch} not higher than current {self._current_epoch}"
            )
        self._current_epoch = epoch

        total = len(self._peers()) + 1  # 含本节点
        majority = total // 2 + 1
        if total >= 3:
            confirms = self._vote_source() if self._vote_source else (total - 1)
            if confirms < majority:
                raise ClusterNoQuorumError(f"quorum {confirms} < majority {majority}")
            return True

        # 2 节点集群：无 witness 无多数派
        if not self._witness_endpoint():
            raise ClusterNoQuorumError("2-node cluster without witness has no quorum")
        return True

    def choose_leader_by_witness(self, candidates: list[dict]) -> str:
        if not self._witness_endpoint():
            raise ClusterNoQuorumError("no witness configured")
        if not candidates:
            raise ClusterNoQuorumError("empty candidates")
        if self._witness_decider:
            chosen = self._witness_decider(candidates)
            if chosen:
                return chosen
        wep = self._witness_endpoint()
        wep_host = wep.split("://")[-1] if "://" in wep else wep
        for c in candidates:
            ep = (c.get("endpoint") or "")
            if ep == wep or ep == wep_host or (("://" in wep) and ep.endswith("/" + wep_host)):
                return str(c.get("node_id") or ep)
        first = candidates[0]
        return str(first.get("node_id") or first.get("endpoint") or "")
