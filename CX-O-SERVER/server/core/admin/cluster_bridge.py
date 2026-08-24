"""CX-A ↔ 哨兵集群适配器 + 统一审计帮助函数（对齐 cx_admin.pyi ClusterAdminBridge）。

集群未启用（cluster_manager 为 None）时，查询与写操作统一返回 {"status": "cluster_disabled"}。
本类只做翻译 + 审计；request_id 幂等与 superadmin 权限由 ControlPlane / 路由层负责。
"""
import inspect
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 项目根（c:\\CX-O\\CX-O-SERVER）：本文件位于 server/core/admin/，上层 3 级即项目根。
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ADMIN_AUDIT_PATH = _PROJECT_ROOT / "data" / "admin_audit.jsonl"


def audit_now(
    actor: str,
    level: str,
    action: str,
    target: str,
    summary: str,
    request_id: Optional[str] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """写一条管理面审计日志（JSONL），返回条目 dict。

    优先复用 server.autonomy.safety.audit.AuditStore（对齐 autonomy_audit schema）；不可用则
    直接追加到 _PROJECT_ROOT/data/admin_audit.jsonl。条目对齐 admin_audit.schema.json。
    """
    entry: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:20],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "level": level if level in ("info", "warn", "error") else "info",
        "action": action,
        "target": str(target),
        "summary": summary,
    }
    if request_id:
        entry["request_id"] = request_id
    if detail:
        entry["detail"] = detail

    path = _ADMIN_AUDIT_PATH
    try:
        from server.autonomy.safety.audit import AuditStore

        AuditStore(path=str(path)).append(entry)
    except Exception:
        try:
            import json

            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:  # pragma: no cover - 审计写失败不阻断控制面
            logger.warning(f"AUDIT_WRITE_FAILED: {e}")
    return entry


def _audit_read(limit: int = 50, offset: int = 0) -> list:
    """分页读取管理面审计日志（JSONL，倒序）。"""
    import json

    path = _ADMIN_AUDIT_PATH
    items: list = []
    if not path.exists():
        return items
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"AUDIT_READ_FAILED: {e}")
        return []
    items.reverse()
    return items[offset:offset + max(limit, 1)]


class ClusterAdminBridge:
    """管理面 ↔ 哨兵集群适配器。构造(cluster_manager, auth)。"""

    def __init__(self, cluster_manager: Optional[Any] = None, auth: Optional[Any] = None):
        self.cluster_manager = cluster_manager
        self.auth = auth

    # ---- 只读 ----
    def read_topology(self) -> Dict[str, Any]:
        """读取集群拓扑。"""
        return self._read("topology")

    def read_state(self) -> Dict[str, Any]:
        """读取集群当前状态。"""
        return self._read("state")

    def read_sync_status(self) -> Dict[str, Any]:
        """读取集群同步状态。"""
        return self._read("sync_status")

    def _read(self, method: str) -> Dict[str, Any]:
        if self.cluster_manager is None:
            return {"status": "cluster_disabled"}
        fn = getattr(self.cluster_manager, method, None)
        if not callable(fn):
            return {"status": "cluster_disabled", "detail": f"missing cluster_manager.{method}"}
        try:
            result = fn()
        except Exception as e:
            logger.warning(f"CLUSTER_READ_FAILED[{method}]: {e}")
            return {"status": "error", "error": str(e)}
        if inspect.iscoroutine(result):
            return {"status": "pending", "detail": "async cluster read"}
        return result if isinstance(result, dict) else {"status": "ok", "data": result}

    # ---- 写（翻译 + 审计）----
    def trigger_failover(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._write("trigger_failover", params, "control.trigger_failover")

    def set_role(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._write("set_role", params, "control.set_role")

    def add_peer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._write("add_peer", params, "control.add_peer")

    def remove_peer(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self._write("remove_peer", params, "control.remove_peer")

    def _write(self, method: str, params: Dict[str, Any], action: str) -> Dict[str, Any]:
        if self.cluster_manager is None:
            return {"status": "cluster_disabled"}
        fn = getattr(self.cluster_manager, method, None)
        if not callable(fn):
            return {"status": "cluster_disabled", "detail": f"missing cluster_manager.{method}"}
        params = params or {}
        try:
            result = fn(params) if params else fn()
        except Exception as e:
            audit_now(
                "CX-A", "error", action, str(params), "集群写操作失败",
                detail={"error": str(e)},
            )
            return {"status": "error", "error": str(e)}
        if inspect.iscoroutine(result):
            audit_now("CX-A", "info", action, str(params), "集群写操作已提交(pending)")
            return {"status": "pending", "detail": "async cluster write"}
        audit_now("CX-A", "info", action, str(params), "集群写操作完成")
        return {"status": "ok", "result": result}