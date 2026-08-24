"""CX-A 管理面核心模块。

对齐 public/interface_stub/cx_admin.pyi 契约，提供：
- AdminAuth / AdminManifest / AdminControlPlane / AdminBatchExecutor / InstanceRegistry / ClusterAdminBridge
- AdminError 异常层次（错误码 ADMIN_*）
此包不做强制落盘（默认丢弃），仅在集群/管理写操作处写入审计日志。
"""

from server.core.admin.auth import (
    AdminError,
    AdminDisabledError,
    AdminAuthError,
    AdminForbiddenError,
    AdminReplayError,
    AdminRateLimitedError,
    AdminUnknownActionError,
    AdminServiceError,
    AdminAuth,
)
from server.core.admin.manifest import AdminManifest
from server.core.admin.control_plane import AdminControlPlane
from server.core.admin.batch import AdminBatchExecutor
from server.core.admin.registry import InstanceRegistry
from server.core.admin.cluster_bridge import ClusterAdminBridge, audit_now

__all__ = [
    "AdminError",
    "AdminDisabledError",
    "AdminAuthError",
    "AdminForbiddenError",
    "AdminReplayError",
    "AdminRateLimitedError",
    "AdminUnknownActionError",
    "AdminServiceError",
    "AdminAuth",
    "AdminManifest",
    "AdminControlPlane",
    "AdminBatchExecutor",
    "InstanceRegistry",
    "ClusterAdminBridge",
    "audit_now",
]