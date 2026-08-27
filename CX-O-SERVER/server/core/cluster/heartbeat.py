"""对等心跳：周期心跳 + 多数派确认故障检测 + 优雅下线广播。

- start/stop：asyncio 后台任务，间隔 peer_heartbeat_interval_sec。
- 连续 miss >= miss_threshold 标记 suspect，再经多数派 gossip 确认才算 dead。
- confirm_dead：向其他 peer 请求 gossip("gossip")，多数派返回确认才 True。
- stop：广播 op="leave" 主动下线。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from ._common import ClusterError

log = logging.getLogger(__name__)


def _iso(t=None) -> str:
    from datetime import datetime

    t = t or time.time()
    return datetime.fromtimestamp(t).astimezone().isoformat()


class PeerHeartbeat:
    def __init__(
        self,
        config=None,
        transport=None,
        node_id: str = "",
        role: str = "standby",
        epoch: int = 0,
        last_sync_seq: int = 0,
        state_version: int = 0,
        gossip_fn: callable = None,
    ):
        self._config = config
        self._transport = transport
        self._node_id = node_id
        self._role = role
        self._epoch = epoch
        self._last_sync_seq = last_sync_seq
        self._state_version = state_version
        self._gossip_fn = gossip_fn  # 依赖注入：gossip_fn(peer_endpoint, about) -> bool
        self._interval = float(getattr(config, "peer_heartbeat_interval_sec", 5) or 5) if config else 5
        self._miss_threshold = int(getattr(config, "miss_threshold", 3) or 3) if config else 3
        self._miss: dict[str, int] = {}
        self._suspect: set[str] = set()
        self._dead: set[str] = set()
        self._peer_state: dict[str, dict] = {}
        self._on_dead: callable = None
        self.last_confirm_report: dict = {}  # 最近一次 confirm_dead 的计票报告（含弃权名单）
        self._task: asyncio.Task | None = None
        self._running = False

    # ---- 依赖注入 ----
    def set_on_dead(self, cb):
        self._on_dead = cb

    def set_gossip_fn(self, fn):
        self._gossip_fn = fn

    def set_transport(self, t):
        self._transport = t

    def set_role(self, role):
        self._role = role

    def set_epoch(self, epoch):
        self._epoch = epoch

    def _peers(self):
        if not self._config:
            return []
        return list(getattr(self._config, "peers", []) or [])

    # ---- 生命周期 ----
    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="cluster-heartbeat")

    async def _loop(self):
        try:
            while self._running:
                await self._beat_once()
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    async def _beat_once(self):
        for endpoint in self._peers():
            ok = False
            try:
                ok = await self._ping(endpoint)
            except ClusterError:
                ok = False
            if ok:
                self._miss.pop(endpoint, None)
                self._peer_state[endpoint] = {
                    "state": "healthy",
                    "last_heartbeat": _iso(),
                }
            else:
                self._miss[endpoint] = self._miss.get(endpoint, 0) + 1
                st = self._peer_state.get(endpoint, {})
                if self._miss[endpoint] >= self._miss_threshold:
                    await self._mark_suspect_and_confirm(endpoint)
                else:
                    st = {"state": "suspect", "last_heartbeat": st.get("last_heartbeat")}
                self._peer_state[endpoint] = st

    async def _ping(self, endpoint) -> bool:
        if not self._transport:
            return True
        payload = {
            "node_id": self._node_id,
            "role": self._role,
            "epoch": self._epoch,
            "last_sync_seq": self._last_sync_seq,
            "state_version": self._state_version,
            "load_summary": {},
        }
        try:
            return bool(
                await self._transport.send(
                    endpoint, "heartbeat", self._node_id, uuid.uuid4().hex,
                    seq=0, epoch=self._epoch, payload=payload,
                )
            )
        except ClusterError:
            return False

    async def _mark_suspect_and_confirm(self, endpoint):
        node = self._peer_node_id(endpoint)
        if node in self._dead:
            # 已确认死亡：短路，不再重复确认/触发接管回调，仅持续监控健康/嫌疑状态。
            return
        self.mark_suspect(node)
        if await self.confirm_dead(node):
            self._dead.add(node)

    def _peer_node_id(self, endpoint) -> str:
        # 握手前 peer node_id 未知，以 endpoint 作为监视标识
        return endpoint

    # ---- 状态 ----
    def mark_suspect(self, node_id: str) -> None:
        self._suspect.add(node_id)
        self._peer_state.setdefault(node_id, {"state": "suspect", "last_heartbeat": None})

    def is_suspect(self, node_id: str) -> bool:
        return node_id in self._suspect

    def is_dead(self, node_id: str) -> bool:
        return node_id in self._dead

    async def confirm_dead(self, node_id: str) -> bool:
        """多数派确认：本节点观测 + 其他 peer 真实意见（gossip 应答）构成多数派判定。

        - 每个 peer 返回的是对端对自己本地 miss 记录的真实判断 {"dead": bool}；
        - 网络失败 / 无应答的 peer 视为弃权（不投赞成票），计入 last_confirm_report["abstained"]；
        - 弃权不改变多数派分母（total = peers 数 + 本节点），与既有语义一致。
        """
        if node_id in self._dead:
            # 幂等短路：同节点死亡只触发一次接管，不再重复 confirm / 触发 on_dead 回调。
            return False
        peers = [p for p in self._peers() if p != node_id]
        others_agree = 0
        abstained: list[str] = []
        for endpoint in peers:
            try:
                opinion = await self._ask_gossip(endpoint, node_id)
            except Exception:  # noqa: BLE001 - 问询异常视为弃权
                opinion = None
            if opinion is None:
                abstained.append(endpoint)
            elif opinion:
                others_agree += 1
        total = len(self._peers()) + 1          # 含本节点
        majority = total // 2 + 1
        agreements = 1 + others_agree           # 本节点自身观测也算一票
        result = agreements >= majority
        self.last_confirm_report = {
            "node_id": node_id,
            "agreements": agreements,
            "majority": majority,
            "agree_peers": others_agree,
            "abstained": list(abstained),   # 网络失败弃权的 peer，报告中说明
        }
        log.info(
            "gossip 死亡确认 node=%s agree=%d/%d（含自身1票）多数=%d 弃权=%s → %s",
            node_id, agreements, total, majority, abstained or "无", result,
        )
        if result:
            self._dead.add(node_id)
            self._peer_state[node_id] = {
                "state": "dead",
                "last_heartbeat": self._peer_state.get(node_id, {}).get("last_heartbeat"),
            }
            cb = self._on_dead
            if cb:
                try:
                    cb(node_id)
                except Exception:  # noqa: BLE001
                    pass
        return result

    async def _ask_gossip(self, peer_endpoint: str, about: str) -> bool | None:
        """向对端询问关于 about 的真实死亡意见。

        返回 True/False 为对端实际应答；None 表示网络失败/无应答（弃权）。
        """
        if self._gossip_fn:
            return bool(self._gossip_fn(peer_endpoint, about))
        if not self._transport:
            return True
        payload = {"ask": "dead", "about": about}
        reply = await self._transport.send_with_reply(
            peer_endpoint, "gossip", self._node_id, uuid.uuid4().hex,
            seq=0, epoch=self._epoch, payload=payload,
        )
        if not isinstance(reply, dict):
            return None  # 网络失败 / 服务错误：弃权
        return bool(reply.get("dead"))

    # ---- 接收端：处理对端入站 op ----
    def record_inbound_heartbeat(self, node_id: str, payload: dict) -> dict:
        """接收 heartbeat op：登记来自 node_id 的入站心跳，重置本地 miss 计数。"""
        node_id = str(node_id or "")
        self._miss.pop(node_id, None)
        st = {
            "state": "healthy",
            "last_heartbeat": _iso(),
            "role": payload.get("role"),
            "epoch": payload.get("epoch"),
            "last_sync_seq": payload.get("last_sync_seq"),
            "state_version": payload.get("state_version"),
        }
        self._peer_state[node_id] = st
        return st

    def handle_leave(self, node_id: str) -> None:
        """接收 leave op：标记节点主动离开并清理其嫌疑/死亡跟踪状态。"""
        node_id = str(node_id or "")
        self._miss.pop(node_id, None)
        self._suspect.discard(node_id)
        self._peer_state[node_id] = {"state": "left", "last_heartbeat": None}

    def observation_dead(self, name: str) -> bool:
        """本地真实观测判定：已确认死亡，或连续 miss 达阈值即视为本地判死。"""
        name = str(name or "")
        if not name:
            return False
        if name in self._dead:
            return True
        return self._miss.get(name, 0) >= self._miss_threshold

    def node_status(self) -> dict:
        """{标识: {state, last_heartbeat}}，供 topology 使用。"""
        return dict(self._peer_state)

    async def stop(self):
        """广播主动下线 + 停后台任务。"""
        self._running = False
        if self._transport:
            for endpoint in self._peers():
                try:
                    await self._transport.send(
                        endpoint, "leave", self._node_id, uuid.uuid4().hex,
                        seq=0, epoch=self._epoch,
                        payload={"node_id": self._node_id},
                    )
                except Exception:  # noqa: BLE001
                    continue
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None