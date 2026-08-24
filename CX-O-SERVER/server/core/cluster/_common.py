"""哨兵集群共享基础：错误码、异常契约、路径解析、密钥工具。

接口契约严格对齐 public/interface_stub/cx_cluster.pyi：
错误码枚举 CLUSTER_DISABLED / CLUSTER_AUTH_FAILED / CLUSTER_REPLAYED /
CLUSTER_NO_QUORUM / CLUSTER_DIRTY_TAKEOVER / CLUSTER_SPLIT_BRAIN_RISK / CLUSTER_SERVICE_ERROR。
本模块仅依赖标准库，避免与集群其他模块循环 import。
"""
from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

# ---- 错误码（统一字符串） ----
CLUSTER_DISABLED = "CLUSTER_DISABLED"
CLUSTER_AUTH_FAILED = "CLUSTER_AUTH_FAILED"
CLUSTER_REPLAYED = "CLUSTER_REPLAYED"
CLUSTER_NO_QUORUM = "CLUSTER_NO_QUORUM"
CLUSTER_DIRTY_TAKEOVER = "CLUSTER_DIRTY_TAKEOVER"
CLUSTER_SPLIT_BRAIN_RISK = "CLUSTER_SPLIT_BRAIN_RISK"
CLUSTER_SERVICE_ERROR = "CLUSTER_SERVICE_ERROR"


# ---- 异常契约 ----
class ClusterError(Exception):
    """集群基础异常。error_code 为上述错误码之一。"""

    error_code: str
    message: str

    def __init__(self, error_code: str, message: str = ""):
        super().__init__(message)
        self.error_code = error_code
        self.message = message or str(self)


class ClusterDisabledError(ClusterError):
    """集群未启用。error_code = CLUSTER_DISABLED"""

    def __init__(self, message: str = "cluster unavailable (not enabled)"):
        super().__init__(CLUSTER_DISABLED, message)


class ClusterAuthError(ClusterError):
    """节点间认证失败。error_code = CLUSTER_AUTH_FAILED"""

    def __init__(self, message: str = "cluster_secret mismatch"):
        super().__init__(CLUSTER_AUTH_FAILED, message)


class ClusterReplayError(ClusterError):
    """传输 request_id 重复。error_code = CLUSTER_REPLAYED"""

    def __init__(self, message: str = "repeated request_id"):
        super().__init__(CLUSTER_REPLAYED, message)


class ClusterNoQuorumError(ClusterError):
    """无法形成多数派 / 见证节点缺席。error_code = CLUSTER_NO_QUORUM"""

    def __init__(self, message: str = "no quorum"):
        super().__init__(CLUSTER_NO_QUORUM, message)


class ClusterDirtyTakeoverError(ClusterError):
    """接管校验数据过旧/不完整，拒绝接管（严格红线）。error_code = CLUSTER_DIRTY_TAKEOVER"""

    def __init__(self, message: str = "state too old, refuse takeover"):
        super().__init__(CLUSTER_DIRTY_TAKEOVER, message)


class ClusterSplitBrainRiskError(ClusterError):
    """检测到脑裂风险。error_code = CLUSTER_SPLIT_BRAIN_RISK"""

    def __init__(self, message: str = "split brain risk"):
        super().__init__(CLUSTER_SPLIT_BRAIN_RISK, message)


# ---- 路径解析（基于 _PROJECT_ROOT = parents[3]） ----
_PROJECT_ROOT = Path(__file__).resolve().parents[3]           # == c:\CX-O\CX-O-SERVER
_DATA_DIR = _PROJECT_ROOT / "data" / "cluster"
_IDENTITY_FILE = _DATA_DIR / "node_identity.json"
_PENDING_DIR = _DATA_DIR / "pending"
_SNAPSHOT_DIR = _DATA_DIR / "snapshots"


# ---- 密钥工具（共享密钥 HMAC 认证） ----
def compute_hmac(secret: str, *parts) -> str:
    """基于共享密钥 + 若干片段计算 HMAC-SHA256 十六进制指纹。"""
    msg = "|".join(str(p) for p in parts).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def hmac_matches(secret: str, provided: str, *parts) -> bool:
    expected = compute_hmac(secret, *parts)
    return hmac.compare_digest(provided, expected)


def parse_error_code(body) -> str | None:
    """从 HTTP 响应体中解析统一错误码（兼容 detail 包装）。"""
    if not isinstance(body, dict):
        return None
    code = body.get("error_code")
    if code:
        return code
    detail = body.get("detail")
    if isinstance(detail, dict):
        return detail.get("error_code")
    return None


def build_endpoint(scheme: str, peer_endpoint: str, op: str) -> str:
    """拼接对端集群端点：scheme 前缀 + /cluster/{op}。"""
    base = (peer_endpoint or "").strip()
    if not base:
        raise ValueError("empty peer_endpoint")
    if base.startswith("http://") or base.startswith("https://"):
        url = base.rstrip("/")
    else:
        url = f"{scheme}://{base}".rstrip("/")
    return f"{url}/cluster/{op}"