"""哨兵状态复制器：增量事件流 + 定期快照双轨制。

- emit：本地写变更，主线程同步分配单调递增 seq（itertools.count()）。
- apply_event：幂等重放（已应用 seq 跳过，记录 last_applied_seq per unit）。
- start/stop/flush：后台周期推待发队列 + 按 snapshot_interval_sec 对齐快照。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
import uuid
from pathlib import Path

from ._common import _SNAPSHOT_DIR
from .units import UNIT_REGISTRY

log = logging.getLogger(__name__)

# ---- 边界常量 ----
OUTBOX_MAX = 1000        # outbox 硬上限：超限丢最旧并累计丢弃计数告警（防队头阻塞无限增长）
APPLIED_SEQS_MAX = 5000  # _applied_seqs 容量上限：周期压实保留最新一半（幂等去重窗口）


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
        self._snapshot_dir = Path(_SNAPSHOT_DIR)
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        # 本地状态
        self._last_applied: dict[str, int] = {u: 0 for u in self._units}
        self._last_snapshot_at: dict[str, str] = {}
        self._seq = itertools.count(1)  # 单调递增 seq（主线程同步接 seq）
        self._outbox: list[dict] = []   # 待推事件（有序）
        # 每个 unit 实际已应用过的 seq 集合：精确幂等判据，避免高水位 last_applied 误杀缺口补投的前序事件。
        self._applied_seqs: dict[str, set[int]] = {}
        self._snapshot_providers: dict[str, callable] = {}
        # outbox 溢出丢弃累计计数（可观测）
        self._dropped_events = 0
        # 溢出 error 告警一次性标记（防风暴：warning 已逐次留痕，error 只提示对齐建议一次）
        self._drop_alerted = False
        # M5: 纪元注入——出站事件携带真实 epoch；接收端过期纪元闸门
        self._epoch_provider: callable = None    # fn() -> 当前纪元（manager 注入 failover.epoch）
        self._leader_provider: callable = None   # fn() -> 当前 leader node_id（非当前 leader 的旧纪元事件拒收）
        self._max_seen_epoch = 0                 # 本地已见最大纪元（内存跟踪即可）
        self._task: asyncio.Task | None = None
        self._running = False

    # ---- 依赖注入 ----
    def set_transport(self, transport):
        self._transport = transport

    def set_epoch_provider(self, fn):
        """注入当前纪元提供者 fn() -> int（出站 sync_event 使用）。"""
        self._epoch_provider = fn

    def set_leader_provider(self, fn):
        """注入当前 leader 判定 fn() -> node_id（空串表示未知；用于旧纪元事件豁免）。"""
        self._leader_provider = fn

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
        # 本地已应用 seq 亦登记，保证对端同 seq 重放被幂等跳过。
        self._applied_seqs.setdefault(unit, set()).add(seq)
        # outbox 硬上限：队头阻塞时丢最旧并告警，防无界增长
        if len(self._outbox) >= OUTBOX_MAX:
            evicted = self._outbox.pop(0)
            self._dropped_events += 1
            log.warning(
                "[replicator] outbox 达上限 %d，丢弃最旧事件 unit=%s seq=%s 累计丢弃=%d",
                OUTBOX_MAX, evicted.get("unit"), evicted.get("seq"), self._dropped_events,
            )
            # M12: 溢出升级告警（一次性）——提示人工/运维触发快照对齐，不做自动对齐
            if not self._drop_alerted:
                self._drop_alerted = True
                log.error(
                    "[replicator] outbox 溢出已开始丢弃事件（累计=%d），"
                    "建议触发快照对齐以防各节点数据缺口扩大",
                    self._dropped_events,
                )
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
                self._compact_applied_seqs()
                now = time.monotonic()
                if now - last_snapshot >= self._snapshot_interval_sec:
                    await self._try_snapshot()
                    last_snapshot = now
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    def _compact_applied_seqs(self):
        """_applied_seqs 周期容量压实。

        对端 ack 水位只覆盖本端发出事件的确认，无法作为入站幂等窗口的裁剪依据；故采用最简正确的容量压实：超过 APPLIED_SEQS_MAX 时保留最新一半 seq，
        兼顾内存有界与"近期重复事件仍可幂等跳过"。极旧重复投递（超出窗口）会被重新应用，
        由各单元应用层自身的幂等语义兜底。
        """
        for unit, seqs in list(self._applied_seqs.items()):
            if len(seqs) > APPLIED_SEQS_MAX:
                keep = set(sorted(seqs)[-APPLIED_SEQS_MAX // 2:])
                self._applied_seqs[unit] = keep
                log.info(
                    "[replicator] applied_seqs 压实 unit=%s %d → %d",
                    unit, len(seqs), len(keep),
                )

    def _peers(self):
        if not self._config:
            return []
        return list(getattr(self._config, "peers", []) or [])

    async def _send_event(self, peers: list, ev: dict) -> bool:
        if not self._transport:
            return False
        # M5: 携带真实纪元（此前硬编码 0），供接收端做旧主回归双写防护
        try:
            cur_epoch = int(self._epoch_provider()) if self._epoch_provider else 0
        except Exception:  # noqa: BLE001 - 纪元取值失败退回 0，不阻断事件流
            cur_epoch = 0
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
                epoch=cur_epoch,
                payload=payload,
            )
            if not ok:
                return False
        return True

    async def _drain(self):
        if not self._outbox:
            return
        peers = self._peers()
        # 顺序发送：按对端已应用水位推进。某事件任一 peer 未确认即停止，保证 outbox 无 seq 缺口
        #（当前序失败时，后序不得先被对端应用并删除，否则补投前序会被对端高水位误判为已应用而丢弃）。
        for ev in list(self._outbox):
            ok = False
            try:
                ok = await self._send_event(peers, ev)
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                break  # 前序未确认：保留后续，下次外层循环从首事件重试
            try:
                self._outbox.remove(ev)
            except ValueError:
                pass

    async def _try_snapshot(self):
        """对每个已注册快照 provider 采集快照并真实落盘到 `data/cluster/snapshots`。

        每个 provider 的 blob 序列化为 ``{unit}.json``，供对等对齐 / 接管恢复使用。
        H8b: build_snapshot 为同步重 IO（读音频文件 + base64 编码），在 async 循环
        内必须经线程池执行，不得直接阻塞事件循环。
        """
        for unit in list(self._snapshot_providers):
            try:
                blob = await asyncio.to_thread(self._backup_provider, unit)
                if blob is not None:
                    self._write_snapshot(unit, blob)
                    self._last_snapshot_at[unit] = _iso()
            except Exception as e:  # noqa: BLE001 - 快照失败不影响事件流，但必须留痕告警
                log.warning("[replicator] 快照采集/落盘失败 unit=%s error=%s", unit, e)

    def _write_snapshot(self, unit: str, blob: dict) -> None:
        """原子写入单单元快照文件。"""
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._snapshot_dir / f".{unit}.json.tmp"
        target = self._snapshot_dir / f"{unit}.json"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(blob, f, ensure_ascii=False, indent=2)
        import os
        os.replace(tmp, target)

    def apply_snapshot(self, unit: str, blob: dict) -> bool:
        """对等对齐/接管恢复：把远端单元快照应用到本机。

        目前仅 ref_audio 有落盘接收端（解包写 ref_audio_assets）。其余单元返回 False。
        """
        if unit != "ref_audio":
            return False
        try:
            from server import ref_audio_store

            ref_audio_store.restore_snapshot(blob)
            return True
        except Exception:  # noqa: BLE001
            return False

    # ---- 幂等重放 ----
    async def apply_event(self, event: dict) -> bool:
        unit = event.get("unit")
        seq = event.get("seq")
        if unit is None or seq is None:
            return False
        # M5: 过期纪元闸门——旧主回归（epoch 落后于本地已见最大值）且来源非当前
        # leader 时拒绝该事件，防止双写。事件无 epoch 字段时跳过闸门（兼容既有契约）。
        epoch_raw = event.get("epoch")
        if epoch_raw is not None:
            try:
                ev_epoch = int(epoch_raw)
            except (TypeError, ValueError):
                ev_epoch = 0
            if ev_epoch < self._max_seen_epoch:
                leader = ""
                if self._leader_provider:
                    try:
                        leader = str(self._leader_provider() or "")
                    except Exception:  # noqa: BLE001
                        leader = ""
                source = str(event.get("node_id") or "")
                if source != leader:
                    log.warning(
                        "[replicator] 拒绝过期纪元事件 unit=%s seq=%s epoch=%d < 本地已见最大 %d "
                        "来源=%s（非当前 leader），疑似旧主回归",
                        unit, int(seq), ev_epoch, self._max_seen_epoch, source or "unknown",
                    )
                    return False
            elif ev_epoch > self._max_seen_epoch:
                self._max_seen_epoch = ev_epoch
        # 精确幂等：以"实际已应用过"判定，而非"seq <= last"高水位判定。
        # 这样即使先序事件曾发送失败、后序已将 last_applied 前移，补投的先序事件（缺口）
        # 也不会被误判为已应用而丢弃。
        applied_set = self._applied_seqs.setdefault(unit, set())
        seq = int(seq)
        if seq in applied_set:
            return False  # 已实际应用过，幂等跳过
        applied_set.add(seq)
        self._last_applied[unit] = max(self._last_applied.get(unit, 0), seq)
        if unit == "ref_audio":
            self._apply_ref_audio(event.get("op"), event.get("payload") or {})
        return True

    def _apply_ref_audio(self, op: str, payload: dict) -> None:
        """接收端落盘 ref_audio 事件（资产元数据 / 绑定；音频文件走快照对齐）。

        使用 ref_audio_store 内部幂等写入，不触发 emit hook（避免回环）。
        """
        try:
            from server import ref_audio_store

            if op == "asset_register":
                asset = payload.get("asset")
                if asset:
                    ref_audio_store._apply_asset_register(asset)
            elif op == "asset_delete":
                ref_audio_store._apply_asset_delete(payload.get("asset_id") or "")
            elif op == "binding_set":
                ref_audio_store._apply_binding(
                    payload.get("agent_id") or "",
                    payload.get("asset_id"),
                    tts_voice=payload.get("tts_voice"),
                    emit=False,
                )
            elif op == "binding_clear":
                ref_audio_store._apply_binding(
                    payload.get("agent_id") or "",
                    None,
                    emit=False,
                )
        except Exception:  # noqa: BLE001 - 接收端落盘失败不阻断 last_applied 推进
            pass

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
        status["_dropped_unsent"] = self._dropped_events
        # M12: 溢出丢弃计数显式字段（与 _dropped_unsent 同值；命名对齐可观测语义）
        status["dropped_events"] = self._dropped_events
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
