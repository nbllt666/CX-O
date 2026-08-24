"""StateReplicator 测试：emit 单调 seq、apply 幂等、sync_status。"""
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