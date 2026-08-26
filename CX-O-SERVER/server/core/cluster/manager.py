"""集群总控：身份/发现/心跳/复制/接管/仲裁装配。

start() 依赖顺序：NodeIdentity → PeerDiscovery → ClusterTransport →
PeerHeartbeat → StateReplicator → ConsensusGuard → FailoverManager，
并启动后台任务。shutdown() 按 replicator.flush → heartbeat.stop 收尾。
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ._common import (
    _DATA_DIR,
    _PENDING_DIR,
    _SNAPSHOT_DIR,
    ClusterDisabledError as _ClusterDisabled,
)
from .consensus import ConsensusGuard
from .discovery import PeerDiscovery
from .failover import FailoverManager
from .heartbeat import PeerHeartbeat
from .identity import NodeIdentity
from .replicator import StateReplicator
from .transport import ClusterTransport
from .units import UNIT_REGISTRY

log = logging.getLogger(__name__)


def _iso(t=None) -> str:
    import time
    from datetime import datetime

    t = t or time.time()
    return datetime.fromtimestamp(t).astimezone().isoformat()


class SentinelCluster:
    def __init__(self, config=None, client=None):
        self._config = config
        self._client = client
        self.data_dir = Path(_DATA_DIR)
        self.pending_dir = Path(_PENDING_DIR)
        self.snapshot_dir = Path(_SNAPSHOT_DIR)
        for d in (self.data_dir, self.pending_dir, self.snapshot_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.identity: NodeIdentity | None = None
        self.discovery: PeerDiscovery | None = None
        self.transport: ClusterTransport | None = None
        self.heartbeat: PeerHeartbeat | None = None
        self.replicator: StateReplicator | None = None
        self.consensus: ConsensusGuard | None = None
        self.failover: FailoverManager | None = None

        self.role = getattr(config, "role", "standby") if config else "standby"
        self._epoch = 0
        self._state_version = 0
        self._event_callbacks: list[callable] = []
        self._started = False
        # E5: 后台接管任务集合——create_task 后跟踪引用并在 shutdown 取消，
        # 避免接管协程在集群停止后仍在 transport/consensus 上做 I/O。
        self._bg_tasks: set = set()

    # ---- 事件（供上层 Aware 订阅） ----
    def set_event_callback(self, cb):
        self._event_callbacks.append(cb)

    def _node_id(self) -> str:
        return getattr(self.identity, "node_id", "") if self.identity else ""

    def emit_event(self, topic: str, **data) -> dict:
        event = {
            "topic": topic if topic.startswith("cluster.") else "cluster." + topic,
            "node_id": self._node_id(),
            "timestamp": _iso(),
            "epoch": self._epoch,
            "data": data,
        }
        for cb in list(self._event_callbacks):
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                log.exception("event callback failed")
        return event

    # ---- 生命周期 ----
    async def start(self):
        if self._started:
            return
        cfg = self._config
        if cfg is None or not getattr(cfg, "enabled", False):
            raise _ClusterDisabled("SentinelCluster not enabled")

        secret = getattr(cfg, "cluster_secret", "") or ""
        node_id = self._build_identity(cfg)
        transport = ClusterTransport(
            config=cfg, secret=secret, node_id=node_id,
            pending_dir=self.pending_dir, client=self._client,
        )
        discovery = PeerDiscovery(
            config=cfg, node_id=node_id, node_name=getattr(self.identity, "node_name", ""),
            role=self.role, endpoint=getattr(self.identity, "endpoint", ""),
            client=self._client, secret=secret,
        )
        consensus = ConsensusGuard(config=cfg, current_epoch=self._epoch)
        heartbeat = PeerHeartbeat(
            config=cfg, transport=transport, node_id=node_id,
            role=self.role, epoch=self._epoch, state_version=self._state_version,
        )
        # B1: 按 config.sync_units 白名单过滤 UNIT_REGISTRY，不再硬编码全量。
        sync_units = getattr(cfg, "sync_units", None) or list(UNIT_REGISTRY.keys())
        active_units = {
            u: UNIT_REGISTRY[u] for u in sync_units if u in UNIT_REGISTRY
        }
        replicator = StateReplicator(
            config=cfg, transport=transport, node_id=node_id,
            units=active_units, pending_dir=self.pending_dir,
        )
        # B1/B2: 注册 ref_audio 快照 provider（打包 ref_audio_assets）+ 接入 emit hook。
        from server import ref_audio_store

        def _ref_audio_snapshot(unit):
            return ref_audio_store.build_snapshot()

        replicator.register_backup_provider("ref_audio", _ref_audio_snapshot)
        ref_audio_store.set_emit_hook(replicator.emit)
        failover = FailoverManager(
            config=cfg, consensus=consensus, node_id=node_id,
            transport=transport, current_epoch=self._epoch,
        )
        failover.set_event_source(self.emit_event)

        # B3: 注入真实 state_source，使"候选状态过旧拒绝接管"红线在生产态真正生效。
        # 候选状态版本取本节点 replicator 已应用事件的总同步深度；集群最小要求版本为
        # 全部 sync_units 至少对齐一次所需的单元数。冷启动/未复制节点会因版本过低被拒。
        def _state_source(dead_node_id):
            last = replicator.last_applied()
            candidate_version = sum(int(v or 0) for v in last.values())
            min_version = len(active_units) if active_units else 1
            return candidate_version, min_version

        failover.set_state_source(_state_source)

        self.transport = transport
        self.discovery = discovery
        self.consensus = consensus
        self.heartbeat = heartbeat
        self.replicator = replicator
        self.failover = failover

        # 心跳确认死亡 → 异步触发接管
        def _schedule_takeover(dead_node_id):
            if not self._started:
                return
            try:
                task = asyncio.get_running_loop().create_task(
                    failover.maybe_takeover(dead_node_id),
                    name="cluster-takeover",
                )
                # E5: 登记后台任务，shutdown 时统一取消，防泄漏
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except RuntimeError:
                pass

        heartbeat.set_on_dead(_schedule_takeover)

        await heartbeat.start()
        await replicator.start()
        self._started = True
        self._epoch = failover.epoch
        self.role = failover.role
        log.info("SentinelCluster started node=%s role=%s", self._node_id(), self.role)

    def _build_identity(self, cfg) -> str:
        ident = NodeIdentity()
        node_id = ident.load_or_create(self.data_dir, cfg)
        self.identity = ident
        return node_id

    async def shutdown(self):
        """replicator.flush → heartbeat.stop（主动下线广播）。"""
        if self.replicator:
            try:
                await self.replicator.flush()
            except Exception:  # noqa: BLE001
                log.exception("replicator flush failed")
            try:
                await self.replicator.stop()
            except Exception:  # noqa: BLE001
                log.exception("replicator stop failed")
        if self.heartbeat:
            try:
                await self.heartbeat.stop()
            except Exception:  # noqa: BLE001
                log.exception("heartbeat stop failed")
        # E5: 取消残留的后台接管任务，防止集群停止后任务继续在
        # transport/consensus/ref_audio 上执行 I/O。
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            try:
                await asyncio.gather(*list(self._bg_tasks), return_exceptions=True)
            except Exception:  # noqa: BLE001
                pass
        self._bg_tasks.clear()
        # 停用后断开 ref_audio emit hook（短路，单机零影响）
        try:
            from server import ref_audio_store

            ref_audio_store.set_emit_hook(None)
        except Exception:  # noqa: BLE001
            pass
        self._started = False

    # ---- 查询 ----
    def topology(self) -> list[dict]:
        node_status = self.heartbeat.node_status() if self.heartbeat else {}
        rows = [{
            "node_id": self._node_id(),
            "endpoint": getattr(self.identity, "endpoint", "") if self.identity else "",
            "role": self.role,
            "state": "healthy",
            "last_heartbeat": _iso(),
        }]
        for peer_ep in (getattr(self._config, "peers", []) if self._config else []):
            st = node_status.get(peer_ep, {"state": "unknown", "last_heartbeat": None})
            rows.append({
                "node_id": peer_ep,
                "endpoint": peer_ep,
                "role": "standby",
                "state": st.get("state", "unknown"),
                "last_heartbeat": st.get("last_heartbeat"),
            })
        return rows

    def state(self) -> dict:
        return {
            "node_id": self._node_id(),
            "role": self.role,
            "epoch": self._epoch,
            "enabled": True,
            "peers": list(getattr(self._config, "peers", []) or []) if self._config else [],
            "identity": {
                "node_name": getattr(self.identity, "node_name", "") if self.identity else "",
                "endpoint": getattr(self.identity, "endpoint", "") if self.identity else "",
            },
        }

    def sync_status(self) -> dict:
        status = {"epoch": self._epoch, "role": self.role}
        if self.replicator:
            status["units"] = self.replicator.sync_status()
        return status

    # ---- 管理桥写操作（ClusterAdminBridge / cluster router 委托） ----

    async def maybe_takeover(self, dead_node_id: str) -> dict:
        """触发对 dead_node_id 的接管（由 FailoverManager 走仲裁与复活）。"""
        if self.failover is None:
            return {"status": "cluster_disabled"}
        try:
            return await self.failover.maybe_takeover(dead_node_id)
        except Exception as e:  # noqa: BLE001
            log.exception("maybe_takeover failed")
            return {"status": "error", "error": str(e)}

    def trigger_failover(self, params: dict) -> dict:
        """手动触发故障转移（superadmin 权限由管理面把关）。"""
        params = params or {}
        from_node = params.get("from_node") or ""
        if not from_node:
            return {"status": "error", "error": "missing from_node"}
        self.emit_event("failover_started", from_node=from_node)
        # 演练路径：构造后台任务执行接管，避免阻塞请求
        try:
            asyncio.get_running_loop().create_task(
                self.maybe_takeover(from_node), name="cluster-manual-failover"
            )
        except RuntimeError:
            pass
        return {"status": "ok", "result": "failover_triggered"}

    def set_role(self, params: dict) -> dict:
        """调整本节点角色（如主动降级为 standby）。"""
        params = params or {}
        role = params.get("role") or ""
        if role not in ("active", "standby", "candidate"):
            return {"status": "error", "error": f"invalid role: {role}"}
        self.role = role
        self.emit_event("role_changed", role=role)
        return {"status": "ok", "role": role}

    def add_peer(self, params: dict) -> dict:
        """增删集群节点（拓扑类；持久化由上层配置完成）。"""
        params = params or {}
        endpoint = params.get("endpoint") or ""
        if not endpoint:
            return {"status": "error", "error": "missing endpoint"}
        peers = list(getattr(self._config, "peers", []) or []) if self._config else []
        if endpoint not in peers:
            peers.append(endpoint)
            if self._config is not None:
                self._config.peers = peers
            self.emit_event("node_joined", endpoint=endpoint)
        return {"status": "ok", "peers": peers}

    def remove_peer(self, params: dict) -> dict:
        params = params or {}
        endpoint = params.get("endpoint") or ""
        peers = list(getattr(self._config, "peers", []) or []) if self._config else []
        if endpoint in peers:
            peers.remove(endpoint)
            if self._config is not None:
                self._config.peers = peers
            self.emit_event("node_left", endpoint=endpoint)
        return {"status": "ok", "peers": peers}
