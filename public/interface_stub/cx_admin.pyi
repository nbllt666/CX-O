"""CX-O 管理面（CX-A）接口契约（core/admin/* + api/routers/admin.py）。

所有异常契约：调用方必须处理约定的异常。
错误码枚举（统一字符串）：ADMIN_DISABLED / ADMIN_AUTH_FAILED / ADMIN_FORBIDDEN /
ADMIN_REPLAYED / ADMIN_RATE_LIMITED / ADMIN_UNKNOWN_ACTION / ADMIN_SERVICE_ERROR。
能力分级：readonly（仅 GET）/ operator（可控制）/ superadmin（可重启/故障转移/增删节点）。
"""
import datetime
from typing import Any, Dict, List, Optional

# ---- 异常契约 ----
class AdminError(Exception):
    """管理面基础异常。error_code 为上述错误码之一。"""
    error_code: str
    message: str

class AdminDisabledError(AdminError):
    """管理面未启用。error_code = ADMIN_DISABLED"""

class AdminAuthError(AdminError):
    """令牌无效 / 未配置 token。error_code = ADMIN_AUTH_FAILED"""

class AdminForbiddenError(AdminError):
    """令牌权限不足（如 readonly 调 operator 动作）。error_code = ADMIN_FORBIDDEN"""

class AdminReplayError(AdminError):
    """request_id 已在防重放缓存中出现过。error_code = ADMIN_REPLAYED"""

class AdminRateLimitedError(AdminError):
    """管理面限流触发。error_code = ADMIN_RATE_LIMITED"""

class AdminUnknownActionError(AdminError):
    """未知 action/target。error_code = ADMIN_UNKNOWN_ACTION"""

# ---- AdminAuth ----
class AdminToken:
    token: str
    level: str  # readonly / operator / superadmin
    name: str

class AdminAuth:
    """多级 token 认证 + request_id 防重放（TTL 缓存）+ 限流。"""
    def authenticate(self, bearer_token: str) -> str: ...  # 返回 level，失败抛 AdminAuthError
    def check_required_level(self, token_level: str, required: str) -> None: ...
    def check_replay(self, request_id: str) -> None: ...  # 重复抛 AdminReplayError
    def check_rate_limit(self) -> None: ...  # 超限抛 AdminRateLimitedError

# ---- AdminManifest ----
class AdminManifest:
    """运行时动态生成自描述能力清单（含集群块）。"""
    def build(self, cluster_state: Optional[Dict[str, Any]]) -> Dict[str, Any]: ...
    def detect_capabilities(self) -> Dict[str, bool]: ...
    def detect_models(self) -> Dict[str, str]: ...

# ---- AdminControlPlane ----
class AdminControlPlane:
    """统一控制入口。对 target=cluster 转发 ClusterAdminBridge。"""
    def dispatch(self, action: str, target: str, request_id: str, agent_id: str, params: Dict[str, Any]) -> Dict[str, Any]: ...
    def _execute(self, target: str, action: str, **kw) -> Dict[str, Any]: ...

# ---- AdminBatchExecutor ----
class AdminBatchExecutor:
    """批量编排。mode=sequential/parallel。返回每步 {step, ok, result, duration_ms}。"""
    def execute(self, request_id: str, mode: str, steps: List[Dict[str, Any]], stop_on_error: bool) -> Dict[str, Any]: ...

# ---- InstanceRegistry ----
class InstanceRegistry:
    """CX-A 多实例注册/发现/心跳表。{instance_id, endpoint, last_heartbeat, role, state}。"""
    def register(self, instance_id: str, endpoint: str, role: str = "active") -> None: ...
    def heartbeat(self, instance_id: str) -> Optional[datetime.datetime]: ...
    def expire_stale(self, timeout_sec: float) -> None: ...
    def snapshot(self) -> List[Dict[str, Any]]: ...

# ---- ClusterAdminBridge ----
class ClusterAdminBridge:
    """管理面 ↔ 哨兵集群适配器。集群未启用时写操作与查询返回 {status: cluster_disabled}。"""
    def read_topology(self) -> Dict[str, Any]: ...
    def read_state(self) -> Dict[str, Any]: ...
    def read_sync_status(self) -> Dict[str, Any]: ...
    def trigger_failover(self, params: Dict[str, Any]) -> Dict[str, Any]: ...
    def set_role(self, params: Dict[str, Any]) -> Dict[str, Any]: ...
    def add_peer(self, params: Dict[str, Any]) -> Dict[str, Any]: ...
    def remove_peer(self, params: Dict[str, Any]) -> Dict[str, Any]: ...