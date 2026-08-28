"""CX-A ↔ 哨兵集群适配器 + 统一审计帮助函数（对齐 cx_admin.pyi ClusterAdminBridge）。

集群未启用（cluster_manager 为 None）时，查询与写操作统一返回 {"status": "cluster_disabled"}。
本类只做翻译 + 审计；request_id 幂等与 superadmin 权限由 ControlPlane / 路由层负责。
"""
import inspect
import logging
import os
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
    """分页读取管理面审计日志（JSONL，倒序）。

    C3 修复：反向块读——seek 到文件尾按 64KB 块向前回退，仅收集末尾
    max(offset + limit, 200) 条（对齐 admin/logs 的 _read_log_tail 模式），
    替代原先全量读入内存再倒序切片的行为。
    """
    import json

    path = _ADMIN_AUDIT_PATH
    if not path.exists():
        return []
    # 需要收集的末尾条数：覆盖 offset+limit 分页窗口（含最小余量 200）
    need = max(offset + max(limit, 1), 200)
    chunk_size = 65536
    data = b""
    pos = None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            while pos > 0 and data.count(b"\n") <= need:
                step = min(chunk_size, pos)
                pos -= step
                f.seek(pos)
                data = f.read(step) + data
    except Exception as e:
        logger.warning(f"AUDIT_READ_FAILED: {e}")
        return []

    segments = data.split(b"\n")
    if pos != 0 and len(segments) > 0:
        segments = segments[1:]  # 首段为跨块的半截行，丢弃（未读到文件头时必不完整）
    items: list = []
    for seg in segments:
        line = seg.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    items.reverse()
    return items[offset:offset + max(limit, 1)]


class PendingClusterResult:
    """async cluster_manager 方法返回的裸协程包装（可等待但不是 coroutine）。

    M-E 修复背景：cluster_manager 的方法绝大多数是同步实现；一旦出现 async
    实现，旧桥接逻辑会把裸协程直接丢弃（_read 返回假 pending、_write 同样
    假提交），管理面永远拿不到真实数据。control_plane._cluster 对桥方法结果
    做 inspect.iscoroutine 判定并把命中项折叠成 {"pending": True}（同样丢
    弃），因此不能把裸协程透传给上层——本包装让协程以"可等待对象"形态穿过
    iscoroutine 检查，交由能 await 的路由层经 resolve_cluster_result() 统一
    解包取回真实结果（admin_control / admin_batch / manifest / status 四条
    路径均已接线）。
    """

    __slots__ = ("_coro",)

    def __init__(self, coro: Any):
        self._coro = coro

    def __await__(self):
        return self._coro.__await__()


async def resolve_cluster_result(value: Any) -> Any:
    """解包结果中内嵌的 PendingClusterResult（M-E，供路由层消费）。

    - Pending 一律 await 还原为真实数据；await 失败转为
      {"status": "error", "error": ...}（不阻断响应组装）；
    - dict 各层嵌套均递归处理（dispatch 外壳会再包一层）；
    - 其余值原样返回。
    """
    if isinstance(value, PendingClusterResult):
        try:
            return await value
        except Exception as e:
            logger.warning(f"CLUSTER_PENDING_RESOLVE_FAILED: {e}")
            return {"status": "error", "error": str(e)}
    if isinstance(value, dict):
        resolved = dict(value)
        for key, item in value.items():
            if isinstance(item, (PendingClusterResult, dict)):
                resolved[key] = await resolve_cluster_result(item)
        return resolved
    return value


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

    def _read(self, method: str) -> Any:
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
            # M-E: 协程不再丢弃——包装为可等待对象交路由层 resolve_cluster_result
            # 解包取真实数据（旧实现返回假 pending 且协程从未被 await）。
            return PendingClusterResult(result)
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

    def _write(self, method: str, params: Dict[str, Any], action: str) -> Any:
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
            # M-E: 协程不再丢弃——审计仅如实声明"已提交待执行"，真实结果由
            # 路由层 resolve_cluster_result await 后返回给调用方。
            audit_now("CX-A", "info", action, str(params), "集群写操作已提交(异步执行中)")
            return PendingClusterResult(result)
        audit_now("CX-A", "info", action, str(params), "集群写操作完成")
        return {"status": "ok", "result": result}