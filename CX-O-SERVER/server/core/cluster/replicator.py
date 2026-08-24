"""哨兵状态复制器：增量事件流 + 定期快照双轨制。

- emit：本地写变更，主线程同步分配单调递增 seq（itertools.count()）。
- apply_event：幂等重放（已应用 seq 跳过，记录 last_applied_seq per unit）。
- start/stop/flush：后台周期推待发队列 + 按 snapshot_interval_sec 对齐快照。
"""
from __future__ import annotations

import asyncio
import itertools
import time
import uuid

from .units import UNIT_REGISTRY


def _iso(t=None) -> str:
    from datetime import datetime

    t = t or time.time()
    return datetime.fromtimestamp(t).astimezone().isoformat()


class StateReplicator:
    def __init__(
        self,
        config=None,
        transport=None,
        node_id: str = "",
        units: dict = None,
        pending_dir=None,
        snapshot_interval_sec: float = None,
    ):
        self._config = config
        self._transport = transport
        self._node_id = node_id
        self._registry = dict(UNIT_REGISTRY)
        self._units = dict(units) or dict(UNIT_REGISTRY)
        self._snapshot_interval_sec = (
            snapshot_interval_sec
            or (getattr(config, "snapshot_interval_sec", 300) if config else 300)
            or 300
        )
        self._pending_dir = pending_dir
        # 本地状态
        self._last_applied: dict[str, int] = {u: 0 for u in self._units}
        self._last_snapshot_at: dict[str, str] = {}
        self._seq = itertools.count(1)  # 单调递增 seq（主线程同步接 seq）
        self._outbox: list[dict] = []   # 待推事件（有序）
        self._snapshot_providers: dict[str, callable] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    # ---- 依赖注入 ----
    def set_transport(self, transport):
        self._transport = transport

    def register_backup_provider(self, unit: str, fn: callable):
        """注册快照提供者 fn(unit) -> snapshot（供 _backup_provider 调用）。"""
        self._snapshot_providers[unit] = fn

    def _backup_provider(self, unit: str):
        fn = self._snapshot_providers.get(unit)
        return fn(unit) if fn else None

    # ---- 本地写变更 ----
    def emit(self, unit: str, op: str, payload: dict) -> int:
        if unit not in self._units:
            self._units[unit] = self._registry.get(unit, "incremental")
        seq = next(self._seq)
        event = {
            "seq": seq,
            "unit": unit,
            "op": op,
            "payload": dict(payload or {}),
            "node_id": self._node_id,
            "timestamp": _iso(),
        }
        # 本地应用：主线程同步推进 last_applied（写变更即本地已生效）
        self._last_applied[unit] = seq
        self._outbox.append(event)
        return seq

    @property
    def outbox_len(self) -> int:
        return len(self._outbox)

    # ---- 后台任务 ----
    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="cluster-replicator")

    async def _loop(self):
        last_snapshot = time.monotonic()
        try:
            while self._running:
                await self._drain()
                now = time.monotonic()
                if now - last_snapshot >= self._snapshot_interval_sec:
                    await self._try_snapshot()
                    last_snapshot = now
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    def _peers(self):
        if not self._config:
            return []
        return list(getattr(self._config, "peers", []) or [])

    async def _send_event(self, peers: list, ev: dict) -> bool:
        if not self._transport:
            return False
        payload = {
            "unit": ev["unit"],
            "op": ev["op"],
            "seq": ev["seq"],
            "data": ev["payload"],
            "timestamp": ev["timestamp"],
        }
        for ep in peers:
            ok = await self._transport.send(
                ep,
                "sync_event",
                self._node_id,
                uuid.uuid4().hex,
                seq=ev["seq"],
                epoch=0,
                payload=payload,
            )
            if not ok:
                return False
        return True

    async def _drain(self):
        if not self._outbox:
            return
        peers = self._peers()
        for ev in list(self._outbox):
            ok = False
            try:
                ok = await self._send_event(peers, ev)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                try:
                    self._outbox.remove(ev)
                except ValueError:
                    pass

    async def _try_snapshot(self):
        for unit in list(self._snapshot_providers):
            try:
                self._backup_provider(unit)
                self._last_snapshot_at[unit] = _iso()
            except Exception:  # noqa: BLE001
                pass

    # ---- 幂等重放 ----
    async def apply_event(self, event: dict) -> bool:
        unit = event.get("unit")
        seq = event.get("seq")
        if unit is None or seq is None:
            return False
        last = self._last_applied.get(unit, 0)
        if seq <= last:
            return False  # 已应用，幂等跳过
        self._last_applied[unit] = int(seq)
        return True

    def last_applied(self) -> dict:
        return dict(self._last_applied)

    def sync_status(self) -> dict:
        outbox_units = [e["unit"] for e in self._outbox]
        status = {}
        for unit in self._units:
            later = sum(1 for u in outbox_units if u == unit)
            status[unit] = {
                "strategy": self._units[unit],
                "last_applied_seq": self._last_applied.get(unit, 0),
                "later_events": later,
                "last_snapshot_at": self._last_snapshot_at.get(unit),
            }
        status["_pending_outbox"] = len(self._outbox)
        return status

    async def flush(self):
        """尽力推给 peer（关闭时）。"""
        await self._drain()

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 - 取消引发的异常忽略
                pass
        self._task = None