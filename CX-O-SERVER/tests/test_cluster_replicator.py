"""StateReplicator 测试：emit 单调 seq、apply 幂等、sync_status、epoch 闸门（M5）。"""
import asyncio
from types import SimpleNamespace

import pytest

from server.core.cluster.replicator import StateReplicator
from server.core.cluster.units import UNIT_REGISTRY


def make_config():
    return SimpleNamespace(peers=[], snapshot_interval_sec=60)


@pytest.mark.asyncio
async def test_emit_monotonic_seq_and_outbox():
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    s1 = rep.emit("memory", "upsert", {"id": 1})
    s2 = rep.emit("memory", "upsert", {"id": 2})
    s3 = rep.emit("session", "write", {"id": 3})
    assert s2 > s1 > 0
    assert s3 > s2  # 跨 unit 也全局单调
    assert rep.outbox_len == 3


@pytest.mark.asyncio
async def test_apply_event_idempotent_by_seq(monkeypatch):
    # E13 后仅 ref_audio 有应用端；桩掉应用层以聚焦本用例原意图：replicator 层 seq 幂等语义
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    monkeypatch.setattr(rep, "_apply_ref_audio", lambda op, payload: True)
    # 首次应用 seq=5
    assert await rep.apply_event({"unit": "ref_audio", "seq": 5, "op": "x", "payload": {}}) is True
    # 同一 seq 重放 → 幂等跳过
    assert await rep.apply_event({"unit": "ref_audio", "seq": 5, "op": "x", "payload": {}}) is False
    # 更高 seq → 应用
    assert await rep.apply_event({"unit": "ref_audio", "seq": 6, "op": "y", "payload": {}}) is True
    assert rep.last_applied()["ref_audio"] == 6


@pytest.mark.asyncio
async def test_emit_then_apply_same_seq_is_idempotent(monkeypatch):
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    monkeypatch.setattr(rep, "_apply_ref_audio", lambda op, payload: True)
    seq = rep.emit("ref_audio", "binding_set", {"agent_id": "a"})  # emit 已本地应用 last_applied
    # 对同一 seq 的入站事件重放 → 跳过
    assert await rep.apply_event({"unit": "ref_audio", "seq": seq, "op": "binding_set", "payload": {}}) is False
    assert await rep.apply_event({"unit": "ref_audio", "seq": seq + 1, "op": "binding_set", "payload": {}}) is True


@pytest.mark.asyncio
async def test_sync_status_reports_last_applied_and_later_events():
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    rep.emit("memory", "upsert", {})
    rep.emit("memory", "upsert", {})
    rep.emit("session", "write", {})
    status = rep.sync_status()
    assert status["memory"]["last_applied_seq"] >= 1
    assert status["memory"]["later_events"] == 2
    assert status["memory"]["strategy"] == "incremental"
    assert status["session"]["later_events"] == 1
    assert status["_pending_outbox"] == 3


# ---------------- M5: 纪元真实化 + 接收端过期纪元闸门 ----------------

class _RecordingTransport:
    """记录 send 调用的 epoch 参数。"""

    def __init__(self):
        self.epochs = []

    async def send(self, peer_endpoint, op, node_id, request_id, seq=0, epoch=0, payload=None):
        self.epochs.append(epoch)
        return True


@pytest.mark.asyncio
async def test_send_event_carries_real_epoch_from_provider():
    """M5：出站 sync_event 的 epoch 取自注入的纪元提供者，不再硬编码 0。"""
    cfg = SimpleNamespace(peers=["p1"], snapshot_interval_sec=60)
    t = _RecordingTransport()
    rep = StateReplicator(config=cfg, transport=t, node_id="me", units={"memory": "incremental"})
    rep.set_epoch_provider(lambda: 7)
    rep.emit("memory", "upsert", {"k": "v"})
    await rep._drain()
    assert t.epochs == [7]


@pytest.mark.asyncio
async def test_apply_event_rejects_stale_epoch_from_non_leader(monkeypatch):
    """M5：event_epoch < 本地已见最大值且来源非当前 leader → 拒绝（防旧主回归双写）。"""
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    monkeypatch.setattr(rep, "_apply_ref_audio", lambda op, payload: True)  # 隔离应用层（E13）
    # 先见过 epoch=5 的事件
    assert await rep.apply_event(
        {"unit": "ref_audio", "seq": 1, "op": "x", "payload": {}, "node_id": "new-master", "epoch": 5}
    ) is True
    # 旧主（非当前 leader）以过期 epoch 投递 → 拒绝且不污染幂等集合
    rejected = await rep.apply_event(
        {"unit": "ref_audio", "seq": 2, "op": "x", "payload": {}, "node_id": "old-master", "epoch": 3}
    )
    assert rejected is False
    assert 2 not in rep._applied_seqs["ref_audio"]
    assert rep.last_applied()["ref_audio"] == 1
    # 之后正常新纪元事件仍可应用
    assert await rep.apply_event(
        {"unit": "ref_audio", "seq": 2, "op": "x", "payload": {}, "node_id": "new-master", "epoch": 6}
    ) is True


@pytest.mark.asyncio
async def test_stale_epoch_exempt_when_source_is_current_leader(monkeypatch):
    """M5：来源为当前 leader 时豁免旧纪元事件。"""
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    monkeypatch.setattr(rep, "_apply_ref_audio", lambda op, payload: True)  # 隔离应用层（E13）
    rep.set_leader_provider(lambda: "the-leader")
    assert await rep.apply_event(
        {"unit": "ref_audio", "seq": 1, "op": "x", "payload": {}, "node_id": "other", "epoch": 9}
    ) is True
    assert await rep.apply_event(
        {"unit": "ref_audio", "seq": 2, "op": "x", "payload": {}, "node_id": "the-leader", "epoch": 4}
    ) is True  # leader 豁免


@pytest.mark.asyncio
async def test_event_without_epoch_skips_gate_compat(monkeypatch):
    """M5 兼容：无 epoch 字段的事件跳过闸门，既有契约不变。"""
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    monkeypatch.setattr(rep, "_apply_ref_audio", lambda op, payload: True)  # 隔离应用层（E13）
    assert await rep.apply_event({"unit": "ref_audio", "seq": 3, "op": "x", "payload": {}}) is True
    assert rep._max_seen_epoch == 0  # 未吸收任何纪元


# ---------------- M12: 溢出可观测性 ----------------

def test_sync_status_exposes_dropped_events_field(monkeypatch):
    from server.core.cluster import replicator as rep_mod

    monkeypatch.setattr(rep_mod, "OUTBOX_MAX", 2)
    rep = StateReplicator(config=make_config(), node_id="me", units={"memory": "incremental"})
    for i in range(4):
        rep.emit("memory", "upsert", {"i": i})
    status = rep.sync_status()
    assert status["dropped_events"] == 2          # M12 新增显式字段
    assert status["_dropped_unsent"] == 2         # 既有键保持兼容


# ---------------- E12/E13/E15: 队头阻塞消除 / 假应用拒绝 ack / 循环自愈 ----------------

class _TwoPeerTransport:
    """E12 双 peer fake transport：peer A 恒失败、peer B 成功。"""

    def __init__(self):
        self.sent = []  # (peer_endpoint, seq)

    async def send(self, peer_endpoint, op, node_id, request_id, seq=0, epoch=0, payload=None):
        self.sent.append((peer_endpoint, seq))
        return peer_endpoint != "dead-peer"


@pytest.mark.asyncio
async def test_drain_not_blocked_by_dead_peer():
    """E12：单 peer 宕机不阻塞健康 peer——任一 peer 成功事件即确认推进，outbox 不积压。"""
    cfg = SimpleNamespace(peers=["dead-peer", "live-peer"], snapshot_interval_sec=60)
    t = _TwoPeerTransport()
    rep = StateReplicator(config=cfg, transport=t, node_id="me", units={"memory": "incremental"})
    rep.emit("memory", "upsert", {"k": 1})
    rep.emit("memory", "upsert", {"k": 2})
    await rep._drain()
    assert rep.outbox_len == 0  # 健康 peer 成功 → 事件确认移出，不再队头阻塞
    assert [s for ep, s in t.sent if ep == "live-peer"] == [1, 2]  # 健康 peer 全部送达
    assert [s for ep, s in t.sent if ep == "dead-peer"] == [1, 2]  # 宕机 peer 仍被尽力尝试


@pytest.mark.asyncio
async def test_drain_breaks_when_all_peers_fail():
    """E12：全部 peer 失败 → 停止本轮 drain，保留队头事件待下轮重试（防重试风暴）。"""

    class _AlwaysFailTransport:
        async def send(self, peer_endpoint, op, node_id, request_id, seq=0, epoch=0, payload=None):
            return False

    cfg = SimpleNamespace(peers=["p1", "p2"], snapshot_interval_sec=60)
    rep = StateReplicator(
        config=cfg, transport=_AlwaysFailTransport(), node_id="me",
        units={"memory": "incremental"},
    )
    rep.emit("memory", "upsert", {"k": 1})
    await rep._drain()
    assert rep.outbox_len == 1  # 无人成功 → 不确认，保留重投


@pytest.mark.asyncio
async def test_apply_event_rejects_unit_without_applier():
    """E13：非 ref_audio 单元暂无应用端 → 拒绝 ack（False 且不登记 seq），发送端保留重投。"""
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    ok = await rep.apply_event({"unit": "memory", "seq": 10, "op": "upsert", "payload": {"id": 1}})
    assert ok is False
    assert 10 not in rep._applied_seqs.get("memory", set())  # 不登记 seq → 接收端不回 ack
    assert rep.last_applied()["memory"] == 0  # 本地零变更，杜绝假确认丢数据


@pytest.mark.asyncio
async def test_loop_survives_unexpected_exception_and_keeps_draining(monkeypatch):
    """E15：_loop 循环体抛未预期异常 → 留痕后自愈继续 drain，task 不死亡、不停摆。"""
    from types import SimpleNamespace as _NS

    from server.core.cluster import replicator as rep_mod

    rep = StateReplicator(config=make_config(), node_id="me", units={"memory": "incremental"})
    calls = {"drain": 0, "raised": 0}

    async def flaky_drain():
        calls["drain"] += 1
        if calls["drain"] == 1:
            calls["raised"] += 1
            raise RuntimeError("unexpected boom")
        await asyncio.sleep(0)  # 自愈轮：正常让出控制权

    monkeypatch.setattr(rep, "_drain", flaky_drain)

    real_sleep = asyncio.sleep

    async def instant_sleep(_delay):
        await real_sleep(0)  # 压缩轮询间隔加速测试（捕获原函数避免自递归）

    # 仅替换 replicator 模块可见的 asyncio 命名空间，不污染全局 asyncio
    monkeypatch.setattr(
        rep_mod, "asyncio",
        _NS(sleep=instant_sleep, create_task=asyncio.create_task,
            to_thread=asyncio.to_thread, CancelledError=asyncio.CancelledError),
    )

    rep._running = True
    task = asyncio.create_task(rep._loop())
    try:
        for _ in range(200):
            await real_sleep(0)
            if calls["drain"] >= 2:
                break
        rep._running = False
        await asyncio.wait_for(task, timeout=5)
    finally:
        rep._running = False
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    assert calls["raised"] == 1  # 第一轮确实抛出了未预期异常
    assert calls["drain"] >= 2   # 异常后循环未死亡，继续 drain（自愈）