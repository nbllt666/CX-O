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

    def snapshot_units(self) -> list:
        """已注册快照 provider 的单元列表（E14：供接管门槛度量"真实同步单元集"）。"""
        return list(self._snapshot_providers)

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
                # E15 自愈：循环体内未预期异常留痕后继续循环（防止 task 死亡且
                # _running 仍 True → start() 幂等守卫拒绝重启 → 复制静默永久停摆）。
                # CancelledError 属 BaseException，不会被下方 except Exception 吞掉，
                # 正常穿透到外层分支退出。
                try:
                    await self._drain()
                    self._compact_applied_seqs()
                    now = time.monotonic()
                    if now - last_snapshot >= self._snapshot_interval_sec:
                        await self._try_snapshot()
                        last_snapshot = now
                except Exception:  # noqa: BLE001 - 单轮失败留痕，下一轮自愈
                    log.exception("[replicator] 复制循环出现未预期异常，%.1fs 后继续（自愈）", 1.0)
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
        # E12 队头阻塞修复：遍历全部 peer 尽力发送，任一成功即确认（不变量"seq 推进
        # 必须有 peer 成功"保持不变）。单 peer 宕机不再放弃后续健康 peer 的复制，
        # 也不再造成 outbox 队头阻塞涨满丢事件；失败 peer 的缺口由精确幂等（B4）
        # 与快照对齐兜底。
        if not peers:
            return True  # 无 peer（单机模式）：无事可同步，视为成功避免 outbox 积压
        any_ok = False
        for ep in peers:
            try:
                ok = await self._transport.send(
                    ep,
                    "sync_event",
                    self._node_id,
                    uuid.uuid4().hex,
                    seq=ev["seq"],
                    epoch=cur_epoch,
                    payload=payload,
                )
            except Exception as e:  # noqa: BLE001 - 单 peer 异常留痕，不阻断其余 peer
                log.warning(
                    "[replicator] 事件发送异常 peer=%s unit=%s seq=%s error=%s",
                    ep, ev["unit"], ev["seq"], e,
                )
                continue
            if ok:
                any_ok = True
            else:
                log.warning(
                    "[replicator] 事件发送失败 peer=%s unit=%s seq=%s（该 peer 出现缺口，"
                    "待重投/快照对齐；单 peer 失败不阻塞健康 peer）",
                    ep, ev["unit"], ev["seq"],
                )
        return any_ok

    async def _drain(self):
        if not self._outbox:
            return
        peers = self._peers()
        # 顺序发送：按 seq 顺序逐事件推进；_send_event 任一 peer 成功即确认并移出
        # outbox（单 peer 失败不阻塞健康 peer，E12）。仅当全部 peer 失败时停止本轮，
        # 保留队头事件待下次循环重试（避免无谓重试风暴）；失败 peer 的缺口由精确
        # 幂等（B4，补投前序不会被高水位误杀）与快照对齐兜底。
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
        # B4 假应用修复：先应用、成功后才登记 seq。旧实现先 add(seq) 再应用、
        # 且应用函数吞异常，落盘失败的事件也被标记"已应用"→ 发送端不再重投 → 丢数据。
        # 现应用失败不登记，返回 False 让接收端回 acked_seq=0、发送端保留 outbox 重投。
        # E13 假应用修复（扩展到全部单元）：仅 ref_audio 实现了落盘应用端。其余单元
        # （memory/session/persona/config/graph/autonomy/vector）当前无接收端实现，
        # 旧实现直接登记 seq + ack → 发送端删 outbox 但本地零变更（假确认丢数据，
        # 与 units.py 声明的 incremental 契约不符）。现拒绝 ack（return False 且不登记
        # seq），发送端保留事件重试；待实现对应应用端后放开。
        if unit != "ref_audio":
            log.warning(
                "[replicator] 单元 %s 暂无应用端实现，拒绝 ack（不登记 seq，发送端重投） "
                "seq=%s op=%s",
                unit, seq, event.get("op"),
            )
            return False
        ok = self._apply_ref_audio(event.get("op"), event.get("payload") or {})
        if not ok:
            log.warning(
                "[replicator] ref_audio 事件应用失败，不登记 seq（等待重投） "
                "unit=%s seq=%s op=%s",
                unit, seq, event.get("op"),
            )
            return False
        applied_set.add(seq)
        self._last_applied[unit] = max(self._last_applied.get(unit, 0), seq)
        return True

    def _apply_ref_audio(self, op: str, payload: dict) -> bool:
        """接收端落盘 ref_audio 事件（资产元数据 / 绑定；音频文件走快照对齐）。

        使用 ref_audio_store 内部幂等写入，不触发 emit hook（避免回环）。
        B4: 返回应用成败——失败（异常/未知 op）返回 False，由调用方留痕并
        不登记 seq，让发送端重投；不再静默吞异常造成"假应用丢数据"。
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
            else:
                # 未知 op：按失败处理（不登记 seq），发送端重投；持续失败由
                # 告警留痕暴露，必要时走快照对齐
                log.warning("[replicator] 未知的 ref_audio op=%s，按应用失败处理", op)
                return False
            return True
        except Exception as e:  # noqa: BLE001 - 应用失败必须可见，交由发送端重投
            log.warning("[replicator] ref_audio 事件落盘失败 op=%s error=%s", op, e)
            return False

    def last_applied(self) -> dict:
        return dict(self._last_applied)

    def is_seq_applied(self, unit: str, seq: int) -> bool:
        """查询该 unit 的 seq 是否已在本地实际应用过（B4）。

        供接收端（manager._op_sync_event）区分 applied=False 的两种成因：
        - seq 已在幂等集合 → 幂等重放（此前已应用成功）→ 仍回完整 ack；
        - seq 不在集合 → 本次应用失败/被纪元闸门拒绝 → 不回 ack，让发送端重投。
        """
        try:
            return int(seq) in self._applied_seqs.get(str(unit), set())
        except (TypeError, ValueError):
            return False

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
