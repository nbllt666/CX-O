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
    CLUSTER_SERVICE_ERROR,
    ClusterAuthError,
    ClusterDisabledError as _ClusterDisabled,
    compute_hmac,
    hmac_matches,
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

# 接收端合法 op 集合（与 transport 发送侧五 op 一一对应）
PEER_OPS = ("handshake", "heartbeat", "gossip", "sync_event", "leave")


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
        # M4: 最近一次接管继承来源（由 failover 成功回调回写，state() 对外可见）
        self._inherited_from = None
        self._event_callbacks: list[callable] = []
        self._started = False
        # E5: 后台接管任务集合——create_task 后跟踪引用并在 shutdown 取消，
        # 避免接管协程在集群停止后仍在 transport/consensus 上做 I/O。
        self._bg_tasks: set = set()
        # F1 接收端：对端节点登记表 {node_id: {node_name, role, endpoint, last_seen, left}}
        self._peers_registry: dict[str, dict] = {}
        # F5 周期 flush 间隔（秒）
        self._flush_interval_sec = (
            float(getattr(config, "pending_flush_interval_sec", 30) or 30) if config else 30.0
        )

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

        self._wire(cfg)

        await self.heartbeat.start()
        await self.replicator.start()
        # F5: 挂周期 flush 后台任务（发送失败队列防无界增长），纳入 _bg_tasks 统一取消管理
        self._spawn_bg(self._flush_loop(), "cluster-pending-flush")
        self._started = True
        self._epoch = self.failover.epoch
        self.role = self.failover.role
        log.info("SentinelCluster started node=%s role=%s", self._node_id(), self.role)

    def _spawn_bg(self, coro, name: str):
        """创建后台任务并登记进 _bg_tasks，shutdown 时统一取消；无事件循环时静默跳过。"""
        try:
            task = asyncio.get_running_loop().create_task(coro, name=name)
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
        except RuntimeError:
            pass

    async def _flush_loop(self):
        """F5: 周期重试待发队列，避免发送失败条目在磁盘上无限堆积。"""
        interval = max(5.0, float(self._flush_interval_sec))
        while self._started:
            await asyncio.sleep(interval)
            transport = self.transport
            if transport is None or not self._started:
                return
            try:
                await transport.flush_pending()
            except Exception:  # noqa: BLE001 - flush 失败不中断循环
                log.exception("pending queue flush failed")

    def _wire(self, cfg):
        """同步装配全部集群组件（start 的构造部分；单测可独立调用以组装运行时）。"""
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

        # F3: 注入真实 vote_source——读取本地心跳观测（各 peer 健康状态快照），
        # 替换 ConsensusGuard 默认的"全体赞成"。计票口径与 PeerHeartbeat.confirm_dead 一致：
        # 本节点自身观测一票 + 观测 healthy 的对端各一票。
        # H7 修复：healthy 计数按唯一 peer 标识去重（同 peer 的 endpoint 键与
        # node_id 键只计一票），修复双键导致的多数派放大。
        def _local_vote_source() -> int:
            return 1 + heartbeat.vote_observation()

        consensus.set_vote_source(_local_vote_source)

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
            self._spawn_bg(failover.maybe_takeover(dead_node_id), "cluster-takeover")

        heartbeat.set_on_dead(_schedule_takeover)

        # M4: 接管成功回调——把 failover 的 role/epoch/inherited_from 实时回写
        # 到 SentinelCluster 可见状态（此前只在 start 时快照，state()/事件纪元会失真）。
        def _on_takeover_success(role: str, epoch: int, inherited_from):
            self.role = role
            self._epoch = epoch
            self._inherited_from = inherited_from

        failover.set_on_takeover(_on_takeover_success)

        # M5: replicator epoch 接线——出站 sync_event 携带真实纪元；
        # 接收端以"当前 active 节点即 leader"作为豁免判据。
        replicator.set_epoch_provider(lambda: failover.epoch)
        replicator.set_leader_provider(
            lambda: (self._node_id() if getattr(failover, "role", "") == "active" else "")
        )

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
        rows = [{
            "node_id": self._node_id(),
            "endpoint": getattr(self.identity, "endpoint", "") if self.identity else "",
            "role": self.role,
            "state": "healthy",
            "last_heartbeat": _iso(),
        }]
        for peer_ep in (getattr(self._config, "peers", []) if self._config else []):
            # H7 适配：观测键统一为 node_id 后，endpoint 需经映射解析其观测状态
            st = None
            if self.heartbeat is not None:
                st = self.heartbeat.status_for(peer_ep)
            if st is None:
                st = {"state": "unknown", "last_heartbeat": None}
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
            "inherited_from": self._inherited_from,
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

    # ---- F1: 对等接收端（peer_router /cluster/{op} 分派落点） ----

    def register_peer(self, node_id: str, info: dict = None) -> dict:
        """登记对端节点（handshake/heartbeat 入站时刷新），并维护 endpoint↔node_id 别名。"""
        node_id = str(node_id or "")
        if not node_id:
            return {}
        info = info or {}
        entry = self._peers_registry.setdefault(node_id, {"registered_at": _iso()})
        for k in ("node_name", "role", "endpoint"):
            v = info.get(k)
            if v:
                entry[k] = str(v)
        entry["left"] = False
        entry["last_seen"] = _iso()
        # 别名映射：endpoint → node_id，供 gossip/heartbeat 入站跨标识解析
        ep = entry.get("endpoint", "")
        if ep:
            self._peers_registry.setdefault(f"__alias__{ep}", {"node_id": node_id})
        return entry

    def _resolve_node_keys(self, name: str) -> list[str]:
        """把入站标识解析为候选本地观测 key：本身 + registry 内 endpoint↔node_id 互查。"""
        name = str(name or "")
        keys = [name] if name else []
        entry = self._peers_registry.get(name)
        if entry:
            for v in (entry.get("endpoint"), entry.get("node_id")):
                if v and v not in keys:
                    keys.append(str(v))
        alias = self._peers_registry.get(f"__alias__{name}")
        if alias and alias.get("node_id") and alias["node_id"] not in keys:
            keys.append(str(alias["node_id"]))
        return keys

    async def handle_peer_op(self, op: str, body: dict) -> tuple[int, dict]:
        """对端 op 统一入口：鉴权 + 分派。返回 (http_status, 响应体)。

        响应统一 {ok: true/false, ...}；鉴权与发送侧同一套共享密钥 HMAC 约定
        （transport.compute_hmac(secret, node_id, request_id, str(seq), op)）。
        """
        op = str(op or "")
        body = body if isinstance(body, dict) else {}
        if op not in PEER_OPS:
            return 404, {
                "ok": False,
                "error_code": CLUSTER_SERVICE_ERROR,
                "message": f"unknown op: {op}",
            }
        secret = getattr(self._config, "cluster_secret", "") or ""
        node_id = str(body.get("node_id") or "")
        request_id = str(body.get("request_id") or "")
        provided = str(body.get("secret_hmac") or "")
        try:
            seq = int(body.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        # M5: 同步链路携带纪元（sync_event 接收端用它做过期纪元闸门）
        try:
            event_epoch = int(body.get("epoch") or 0)
        except (TypeError, ValueError):
            event_epoch = 0
        payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}

        if not provided:
            return 401, {
                "ok": False,
                "error_code": "CLUSTER_AUTH_FAILED",
                "message": "missing secret_hmac",
            }
        expected_parts = (node_id, request_id, str(seq), op)
        if not node_id or not hmac_matches(secret, provided, *expected_parts):
            return 403, {
                "ok": False,
                "error_code": "CLUSTER_AUTH_FAILED",
                "message": "cluster_secret mismatch",
            }

        handler = {
            "handshake": self._op_handshake,
            "heartbeat": self._op_heartbeat,
            "gossip": self._op_gossip,
            "sync_event": self._op_sync_event,
            "leave": self._op_leave,
        }[op]
        try:
            data = await handler(payload=payload, node_id=node_id, seq=seq, epoch=event_epoch)
        except ClusterAuthError:
            # op 内层密钥证明失败（如 handshake proof）与外层鉴权同口径：403
            return 403, {
                "ok": False,
                "error_code": "CLUSTER_AUTH_FAILED",
                "message": "peer secret proof mismatch",
            }
        except Exception as e:  # noqa: BLE001 - 分派异常收敛为服务错误响应
            log.exception("handle_peer_op failed op=%s from=%s", op, node_id)
            return 500, {"ok": False, "error_code": CLUSTER_SERVICE_ERROR, "message": str(e)}
        return 200, {"ok": True, **(data or {})}

    async def _op_handshake(self, payload: dict, node_id: str, seq: int = 0, epoch: int = 0) -> dict:
        """handshake：验证对端密钥证明 → 登记对端 → 回应己方身份（含自身密钥证明）。"""
        secret = getattr(self._config, "cluster_secret", "") or ""
        proof = str(payload.get("secret_hmac") or "")
        if not hmac_matches(secret, proof, node_id, "handshake", node_id):
            raise ClusterAuthError()
        entry = self.register_peer(node_id, payload)
        # H7：回填 endpoint→node_id 映射，心跳观测键自此统一为 node_id
        ep = (entry or {}).get("endpoint", "")
        if ep and self.heartbeat is not None:
            self.heartbeat.bind_endpoint_node(ep, node_id)
        log.info("[peer] handshake registered node=%s endpoint=%s", node_id, entry.get("endpoint"))
        ident = self.identity
        my_id = self._node_id()
        return {
            "node_id": my_id,
            "epoch": self._epoch,
            "role": self.role,
            "payload": {
                "node_name": getattr(ident, "node_name", "") if ident else "",
                "role": self.role,
                "endpoint": getattr(ident, "endpoint", "") if ident else "",
                "secret_hmac": compute_hmac(secret, my_id, "handshake", my_id),
            },
        }

    async def _op_heartbeat(self, payload: dict, node_id: str, seq: int = 0, epoch: int = 0) -> dict:
        """heartbeat：更新对端存活状态（复用 miss 追踪数据结构）。"""
        st = {}
        if self.heartbeat is not None:
            st = self.heartbeat.record_inbound_heartbeat(node_id, payload)
        entry = self.register_peer(node_id, {"role": payload.get("role")})
        # H7：registry 已知该 node 的 endpoint 时回填映射（通常由先前 handshake 登记）
        ep = (entry or {}).get("endpoint", "")
        if ep and self.heartbeat is not None:
            self.heartbeat.bind_endpoint_node(ep, node_id)
        return {"observed_state": st.get("state", "healthy"), "node_id": self._node_id()}

    async def _op_gossip(self, payload: dict, node_id: str, seq: int = 0, epoch: int = 0) -> dict:
        """gossip：根据本地 miss 记录如实回答关于 about 的死亡意见。

        死亡判据：本地已确认死亡，或连续 miss 达阈值；跨标识经 registry 别名互查。
        """
        about = str(payload.get("about") or "")
        dead = False
        if about:
            keys = self._resolve_node_keys(about)
            if self.heartbeat is not None:
                dead = any(self.heartbeat.observation_dead(k) for k in keys)
        return {"dead": dead, "about": about}

    async def _op_sync_event(self, payload: dict, node_id: str, seq: int = 0, epoch: int = 0) -> dict:
        """sync_event：交 replicator 幂等应用对端事件（seq 去重 + epoch 闸门），成功回 ack 序号。"""
        unit = payload.get("unit")
        event_seq = payload.get("seq", seq)
        if not unit or event_seq is None:
            return {"acked_seq": 0, "applied": False, "reason": "invalid_event"}
        applied = False
        if self.replicator is not None:
            applied = await self.replicator.apply_event({
                "unit": str(unit),
                "seq": int(event_seq),
                "op": payload.get("op"),
                "payload": payload.get("data") or {},
                "node_id": node_id,
                "epoch": int(epoch or 0),
            })
        return {"acked_seq": int(event_seq), "applied": bool(applied)}

    async def _op_leave(self, payload: dict, node_id: str, seq: int = 0, epoch: int = 0) -> dict:
        """leave：标记节点主动离开并触发清理（清嫌疑跟踪 + 广播 node_left）。"""
        who = str(payload.get("node_id") or node_id)
        if self.heartbeat is not None:
            self.heartbeat.handle_leave(who)
        entry = self.register_peer(who) or {}
        entry["left"] = True
        self.emit_event("node_left", node_id=who, graceful=True)
        log.info("[peer] leave received node=%s", who)
        return {"left": who}

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
        # 演练路径：后台任务执行接管，避免阻塞请求（F6: 复用 _spawn_bg 登记进 _bg_tasks）
        self._spawn_bg(self.maybe_takeover(from_node), "cluster-manual-failover")
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
