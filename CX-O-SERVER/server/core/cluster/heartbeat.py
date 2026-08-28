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
        # H7 修复：endpoint→node_id 映射（入站 handshake/heartbeat 时由 manager 回填），
        # 出站观测按此换算观测键，与入站键统一为 node_id，保证互清可达。
        self._endpoint_to_node: dict[str, str] = {}
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
        # B11: 单轮心跳异常不再终止循环——除 CancelledError 保持 cancel 传播外，
        # 其余异常留痕后继续下一轮（否则一次瞬时网络/服务异常会杀掉心跳后台任务，
        # 节点从此不再发心跳、被对端误判死亡）。
        try:
            while self._running:
                try:
                    await self._beat_once()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - 单轮失败留痕后继续循环
                    log.exception("心跳循环异常")
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    # ---- endpoint↔node_id 观测键统一（H7） ----
    def bind_endpoint_node(self, endpoint: str, node_id: str) -> None:
        """登记 endpoint→node_id 映射（manager 在入站 handshake/heartbeat 时回填）。"""
        endpoint = str(endpoint or "")
        node_id = str(node_id or "")
        if endpoint and node_id and endpoint != node_id:
            self._endpoint_to_node[endpoint] = node_id

    def _identity_for_endpoint(self, endpoint) -> str:
        """出站观测键换算：该 endpoint 已知对应 node_id 则用之，否则退回 endpoint 键。"""
        ep = str(endpoint or "")
        return self._endpoint_to_node.get(ep, ep)

    def _unique_peer_identity(self, key) -> str:
        """任意观测键归一到唯一 peer 标识（node_id 优先），供投票去重。"""
        k = str(key or "")
        return self._endpoint_to_node.get(k, k)

    def vote_observation(self) -> int:
        """本节点本地观测健康票数（供 consensus.vote_source）：按唯一 peer 标识去重。

        同一 peer 可能同时存在 endpoint 键与 node_id 键；经 _endpoint_to_node
        归一后只计一次，修复同 peer 双计导致的多数派放大（H7）。
        """
        counted: set[str] = set()
        healthy = 0
        for key, v in self._peer_state.items():
            ident = self._unique_peer_identity(key)
            if ident in counted:
                continue
            counted.add(ident)
            if isinstance(v, dict) and v.get("state") == "healthy":
                healthy += 1
        return healthy

    def status_for(self, endpoint: str):
        """按 endpoint 解析观测状态：优先 endpoint 键，其次其映射的 node_id 键。"""
        ep = str(endpoint or "")
        st = self._peer_state.get(ep)
        if st is not None:
            return st
        node = self._endpoint_to_node.get(ep)
        if node:
            return self._peer_state.get(node)
        return None

    # ---- 复活通道（M3） ----
    def _mark_recovered(self, ident: str) -> None:
        """死亡/嫌疑节点复活：清理跟踪状态并留 RECOVERED 审计日志。

        当前事件契约（cluster_event.schema.json 枚举）无 recover 类主题且 public/
        禁止修改，故采用 logger.warning 级审计日志 + 状态自然恢复方案。
        """
        recovered_states: list[str] = []
        if ident in self._dead:
            self._dead.discard(ident)
            recovered_states.append("dead")
        if ident in self._suspect:
            self._suspect.discard(ident)
            recovered_states.append("suspect")
        self._miss.pop(ident, None)
        st = dict(self._peer_state.get(ident, {}))
        st["state"] = "healthy"
        self._peer_state[ident] = st
        if recovered_states:
            log.warning(
                "[RECOVERED] 节点 %s 从 %s 状态恢复健康", ident, "/".join(recovered_states)
            )

    async def _beat_once(self):
        for endpoint in self._peers():
            # H7：换算到该 endpoint 已知唯一标识后再记账，保证与入站心跳键一致可互清
            ident = self._identity_for_endpoint(endpoint)
            ok = False
            try:
                ok = await self._ping(endpoint)
            except ClusterError:
                ok = False
            if ok:
                was_bad = ident in self._suspect or ident in self._dead
                self._miss.pop(ident, None)
                st = dict(self._peer_state.get(ident, {}))
                st.update({"state": "healthy", "last_heartbeat": _iso()})
                self._peer_state[ident] = st
                if was_bad:
                    self._mark_recovered(ident)
            else:
                self._miss[ident] = self._miss.get(ident, 0) + 1
                if self._miss[ident] >= self._miss_threshold:
                    await self._mark_suspect_and_confirm(ident)
                else:
                    # B11: 就地 update 保留既有元数据（role/epoch/last_sync_seq 等，
                    # 由 record_inbound_heartbeat 写入）——旧实现整 dict 覆盖会清空
                    # 这些字段，破坏 gossip/vote 依赖的观测上下文。prev 不存在才新建。
                    prev = self._peer_state.get(ident)
                    if prev is None:
                        self._peer_state[ident] = {"state": "suspect", "last_heartbeat": None}
                    else:
                        prev.update({"state": "suspect"})

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
        # 排除被确认对象自身（无论以 endpoint 键还是 node_id 形式登记）——不向其问询死亡意见
        peers = [
            p for p in self._peers()
            if p != node_id and self._endpoint_to_node.get(p, p) != node_id
        ]
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
        if node_id and (node_id in self._dead or node_id in self._suspect):
            # M3：入站心跳即复活证据——死亡/嫌疑节点重新现身，走复活通道
            self._mark_recovered(node_id)
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