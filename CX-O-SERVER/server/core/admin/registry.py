"""CX-A 多实例注册/发现/心跳表（对齐 cx_admin.pyi InstanceRegistry 契约）。"""
import logging
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InstanceRegistry:
    """CX-A 多实例注册/发现/心跳表。

    默认仅被动维护本地注册表（不强制落盘）；配置 cx_a_endpoint 时 start() 会周期
    向管理面端点主动注册/上报心跳。实例项结构：
    {instance_id, endpoint, role, last_heartbeat(datetime), state}。
    """

    def __init__(self, register_interval_sec: int = 15, admin_cfg: Optional[Any] = None):
        self.register_interval_sec = int(register_interval_sec or 15)
        self.admin_cfg = admin_cfg
        self._instances: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # 本实例标识（优先来自 admin_cfg，否则 hostname）
        self.instance_id = ""
        if self.admin_cfg is not None:
            self.instance_id = getattr(self.admin_cfg, "instance_id", "") or ""
        if not self.instance_id:
            self.instance_id = f"cxo-{socket.gethostname() or 'node'}"

    # ------------------------------------------------------------------ 注册
    def register(self, instance_id: str, endpoint: str, role: str = "active") -> None:
        """注册或更新一个实例接入点。"""
        if not instance_id:
            return
        with self._lock:
            existing = self._instances.get(instance_id)
            if existing:
                existing["endpoint"] = endpoint
                existing["role"] = role
                existing["last_heartbeat"] = _now()
                existing["state"] = "active"
            else:
                self._instances[instance_id] = {
                    "instance_id": instance_id,
                    "endpoint": endpoint,
                    "role": role,
                    "last_heartbeat": _now(),
                    "state": "active",
                }

    def heartbeat(self, instance_id: str) -> Optional[datetime]:
        """心跳续期；实例不存在时返回 None。"""
        with self._lock:
            inst = self._instances.get(instance_id)
            if inst is None:
                return None
            ts = _now()
            inst["last_heartbeat"] = ts
            inst["state"] = "active"
            return ts

    def expire_stale(self, timeout_sec: float) -> None:
        """移除超过 timeout_sec 未心跳的实例。"""
        now = _now()
        with self._lock:
            stale = [
                iid
                for iid, inst in self._instances.items()
                if _age(inst.get("last_heartbeat"), now) > float(timeout_sec)
            ]
            for iid in stale:
                self._instances.pop(iid, None)

    def snapshot(self) -> List[Dict[str, Any]]:
        """返回实例表快照（时间戳序列化为 ISO8601 字符串，线程安全拷贝）。"""
        with self._lock:
            out = []
            for inst in self._instances.values():
                row = dict(inst)
                row["last_heartbeat"] = (
                    inst["last_heartbeat"].isoformat()
                    if isinstance(inst.get("last_heartbeat"), datetime)
                    else inst.get("last_heartbeat")
                )
                out.append(row)
            return out

    # ------------------------------------------------------------- 后台生命周期
    def start(self) -> None:
        """后台周期主动注册/心跳。cx_a_endpoint 为空时仅做占位（无操作）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="cx-a-instance-registry", daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        """停止后台线程并回收。"""
        self._stop.set()
        thread = getattr(self, "_thread", None)
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
        self._thread = None

    def _run(self) -> None:
        interval = max(1, self.register_interval_sec)
        while not self._stop.is_set():
            try:
                self._active_register()
            except Exception as e:  # pragma: no cover - 后台上报失败降级
                logger.warning(f"PROACTIVE_REGISTER_FAILED: {e}")
            self._stop.wait(interval)

    def _active_register(self) -> None:
        """主动向 cx_a_endpoint 上报 /api/admin/register。未配置端点时无操作。"""
        endpoint = ""
        if self.admin_cfg is not None:
            endpoint = getattr(self.admin_cfg, "cx_a_endpoint", "") or ""
        if not endpoint:
            return
        url = str(endpoint).rstrip("/") + "/api/admin/register"
        payload = {
            "instance_id": self.instance_id,
            "endpoint": url,
            "role": "active",
            "timestamp": _now().isoformat(),
        }
        try:
            import httpx

            httpx.post(url, json=payload, timeout=5)
        except Exception as e:  # pragma: no cover
            logger.warning(f"PROACTIVE_REGISTER_NETWORK: {url} -> {e}")


def _age(ts, now) -> float:
    if isinstance(ts, datetime):
        return (now - ts).total_seconds()
    return float("inf")