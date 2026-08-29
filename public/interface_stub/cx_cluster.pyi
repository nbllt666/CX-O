"""CX-O 哨兵集群接口契约（core/cluster/* + api/routers/cluster.py）。

契约版本: 1.0.1（PATCH，G4-B 签名对齐：confirm_dead 补 async、emit 返回 int、StateReplicator.sync_status 返回结构对齐实现）

所有异常契约：调用方必须处理约定的异常。
错误码枚举（统一字符串）：CLUSTER_DISABLED / CLUSTER_AUTH_FAILED / CLUSTER_REPLAYED /
CLUSTER_NO_QUORUM / CLUSTER_DIRTY_TAKEOVER / CLUSTER_SPLIT_BRAIN_RISK / CLUSTER_SERVICE_ERROR。
铁律：宁可暂不接管，不用残缺/冲突数据错误复活；灵魂数据只在受信节点间流动。
"""
import datetime
from typing import Any, Dict, List, Optional

# ---- 异常契约 ----
class ClusterError(Exception):
    """集群基础异常。error_code 为上述错误码之一。"""
    error_code: str
    message: str

class ClusterDisabledError(ClusterError):
    """集群未启用。error_code = CLUSTER_DISABLED"""

class ClusterAuthError(ClusterError):
    """节点间认证失败（cluster_secret 不匹配）。error_code = CLUSTER_AUTH_FAILED"""

class ClusterReplayError(ClusterError):
    """传输 request_id 重复。error_code = CLUSTER_REPLAYED"""

class ClusterNoQuorumError(ClusterError):
    """无法形成多数派 / 见证节点缺席。error_code = CLUSTER_NO_QUORUM"""

class ClusterDirtyTakeoverError(ClusterError):
    """接管校验数据过旧/不完整，拒绝接管（严格红线）。error_code = CLUSTER_DIRTY_TAKEOVER"""

class ClusterSplitBrainRiskError(ClusterError):
    """检测到脑裂风险。error_code = CLUSTER_SPLIT_BRAIN_RISK"""

# ---- NodeIdentity ----
class NodeIdentity:
    node_id: str
    node_name: str
    endpoint: str
    created_at: str
    def load_or_create(self, data_dir: str, config: Any) -> str: ...  # 返回 node_id

# ---- PeerDiscovery ----
class PeerDiscovery:
    """种子列表主动握手（默认）；UDP 广播可选。cluster_secret 校验。"""
    def discover(self) -> List[Dict[str, Any]]: ...
    async def handshake(self, peer_endpoint: str) -> Dict[str, Any]: ...

# ---- ClusterTransport ----
class ClusterTransport:
    """TLS/HTTPS 节点间传输 + 共享密钥 + request_id/seq 防重放 + 失败入待发队列。"""
    async def send(self, peer_endpoint: str, op: str, node_id: str, request_id: str, seq: int = 0, epoch: int = 0, payload: Optional[Dict[str, Any]] = None) -> bool: ...
    async def flush_pending(self) -> None: ...

# ---- PeerHeartbeat ----
class PeerHeartbeat:
    """周期心跳 + 多数派确认故障检测 + 优雅下线广播。"""
    async def start(self) -> None: ...
    async def stop(self) -> None: ...  # 广播主动下线
    def mark_suspect(self, node_id: str) -> None: ...
    async def confirm_dead(self, node_id: str) -> bool: ...  # 多数派确认后才返回 True（幂等短路返回 False）

# ---- BackupUnit Sentinel 状态复制 ----
class StateReplicator:
    """增量事件流 + 定期快照双轨制；不阻塞主链路；待发队列。"""
    def emit(self, unit: str, op: str, payload: Dict[str, Any]) -> int: ...  # 本地写变更，返回事件 seq
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def flush(self) -> None: ...  # 尽力推给 peer（关闭时）
    async def apply_event(self, event: Dict[str, Any]) -> bool: ...  # 幂等重放
    def sync_status(self) -> Dict[str, Any]: ...  # {unit: {strategy, last_applied_seq, later_events, last_snapshot_at}} + _pending_outbox/_dropped_unsent/dropped_events

class BackupUnit:
    unit: str
    strategy: str  # incremental / snapshot / rebuild
    last_applied_seq: int

# ---- FailoverManager ----
class FailoverManager:
    """接管流程：candidate → epoch+1 → 仲裁 → 复活灵魂（B 继承 A 记忆为遗产）→ active。"""
    async def maybe_takeover(self, dead_node_id: str) -> Dict[str, Any]: ...
    async def adopt_inheritance(self, from_node_id: str) -> None: ...

# ---- ConsensusGuard ----
class ConsensusGuard:
    """epoch 防双主 + 多数派 + 见证节点 tiebreaker + 脏接管拒绝。"""
    def can_takeover(self, from_node_id: str, candidate_state_version: int, min_version: int, epoch: int) -> bool: ...  # 否则抛 ClusterNoQuorum / ClusterDirtyTakeoverError
    def choose_leader_by_witness(self, candidates: List[Dict[str, Any]]) -> str: ...

# ---- SentinelCluster ----
class SentinelCluster:
    """集群总控（身份/发现/心跳/复制/接管/仲裁装配）。"""
    async def start(self) -> None: ...
    async def shutdown(self) -> None: ...
    def topology(self) -> List[Dict[str, Any]]: ...
    def state(self) -> Dict[str, Any]: ...
    def sync_status(self) -> Dict[str, Any]: ...