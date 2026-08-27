"""StateReplicator 测试：emit 单调 seq、apply 幂等、sync_status、epoch 闸门（M5）。"""
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
async def test_apply_event_idempotent_by_seq():
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    # 首次应用 seq=5
    assert await rep.apply_event({"unit": "memory", "seq": 5, "op": "x", "payload": {}}) is True
    # 同一 seq 重放 → 幂等跳过
    assert await rep.apply_event({"unit": "memory", "seq": 5, "op": "x", "payload": {}}) is False
    # 更高 seq → 应用
    assert await rep.apply_event({"unit": "memory", "seq": 6, "op": "y", "payload": {}}) is True
    assert rep.last_applied()["memory"] == 6


@pytest.mark.asyncio
async def test_emit_then_apply_same_seq_is_idempotent():
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    seq = rep.emit("config", "update", {"k": "v"})  # emit 已本地应用 last_applied
    # 对同一 seq 的入站事件重放 → 跳过
    assert await rep.apply_event({"unit": "config", "seq": seq, "op": "update", "payload": {}}) is False
    assert await rep.apply_event({"unit": "config", "seq": seq + 1, "op": "update", "payload": {}}) is True


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
async def test_apply_event_rejects_stale_epoch_from_non_leader():
    """M5：event_epoch < 本地已见最大值且来源非当前 leader → 拒绝（防旧主回归双写）。"""
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    # 先见过 epoch=5 的事件
    assert await rep.apply_event(
        {"unit": "memory", "seq": 1, "op": "x", "payload": {}, "node_id": "new-master", "epoch": 5}
    ) is True
    # 旧主（非当前 leader）以过期 epoch 投递 → 拒绝且不污染幂等集合
    rejected = await rep.apply_event(
        {"unit": "memory", "seq": 2, "op": "x", "payload": {}, "node_id": "old-master", "epoch": 3}
    )
    assert rejected is False
    assert 2 not in rep._applied_seqs["memory"]
    assert rep.last_applied()["memory"] == 1
    # 之后正常新纪元事件仍可应用
    assert await rep.apply_event(
        {"unit": "memory", "seq": 2, "op": "x", "payload": {}, "node_id": "new-master", "epoch": 6}
    ) is True


@pytest.mark.asyncio
async def test_stale_epoch_exempt_when_source_is_current_leader():
    """M5：来源为当前 leader 时豁免旧纪元事件。"""
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    rep.set_leader_provider(lambda: "the-leader")
    assert await rep.apply_event(
        {"unit": "memory", "seq": 1, "op": "x", "payload": {}, "node_id": "other", "epoch": 9}
    ) is True
    assert await rep.apply_event(
        {"unit": "memory", "seq": 2, "op": "x", "payload": {}, "node_id": "the-leader", "epoch": 4}
    ) is True  # leader 豁免


@pytest.mark.asyncio
async def test_event_without_epoch_skips_gate_compat():
    """M5 兼容：无 epoch 字段的事件跳过闸门，既有契约不变。"""
    rep = StateReplicator(config=make_config(), node_id="me", units=UNIT_REGISTRY)
    assert await rep.apply_event({"unit": "memory", "seq": 3, "op": "x", "payload": {}}) is True
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