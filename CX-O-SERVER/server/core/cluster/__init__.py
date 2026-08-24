"""哨兵集群核心包。导出异常契约与轻量类（避免重导入拖慢测试）。"""
from ._common import (
    CLUSTER_DISABLED,
    CLUSTER_AUTH_FAILED,
    CLUSTER_REPLAYED,
    CLUSTER_NO_QUORUM,
    CLUSTER_DIRTY_TAKEOVER,
    CLUSTER_SPLIT_BRAIN_RISK,
    CLUSTER_SERVICE_ERROR,
    ClusterError,
    ClusterDisabledError,
    ClusterAuthError,
    ClusterReplayError,
    ClusterNoQuorumError,
    ClusterDirtyTakeoverError,
    ClusterSplitBrainRiskError,
)
from .units import BackupUnit, UNIT_REGISTRY, describe
from .identity import NodeIdentity

__all__ = [
    "CLUSTER_DISABLED",
    "CLUSTER_AUTH_FAILED",
    "CLUSTER_REPLAYED",
    "CLUSTER_NO_QUORUM",
    "CLUSTER_DIRTY_TAKEOVER",
    "CLUSTER_SPLIT_BRAIN_RISK",
    "CLUSTER_SERVICE_ERROR",
    "ClusterError",
    "ClusterDisabledError",
    "ClusterAuthError",
    "ClusterReplayError",
    "ClusterNoQuorumError",
    "ClusterDirtyTakeoverError",
    "ClusterSplitBrainRiskError",
    "BackupUnit",
    "UNIT_REGISTRY",
    "describe",
    "NodeIdentity",
]