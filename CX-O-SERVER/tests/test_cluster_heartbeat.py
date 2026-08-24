"""PeerHeartbeat 测试：miss→suspect、多数派确认（自 mock 多数）、on_dead 回调。"""
from types import SimpleNamespace

import pytest

from server.core.cluster.heartbeat import PeerHeartbeat


def make_config(**kw):
    cfg = SimpleNamespace(
        peers=["p1", "p2"],
        role="standby",
        peer_heartbeat_interval_sec=1,
        miss_threshold=2,
        transport="https",
    )
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


class _DeadTransport:
    """对某对端心跳恒失败，便于触发 miss 累计。"""

    def __init__(self, dead_peer):
        self.dead_peer = dead_peer
        self.calls = []

    async def send(self, peer_endpoint, op, node_id, request_id, seq=0, epoch=0, payload=None):
        self.calls.append((peer_endpoint, op))
        if peer_endpoint == self.dead_peer and op == "heartbeat":
            return False
        return True


@pytest.mark.asyncio
async def test_miss_increments_and_suspect_after_threshold():
    cfg = make_config(peers=["p1", "p2"], miss_threshold=2)
    t = _DeadTransport("p2")
    hb = PeerHeartbeat(config=cfg, transport=t, node_id="me")
    hb.set_gossip_fn(lambda ep, about: True)  # 全票确认

    await hb._beat_once()  # 第 1 次 miss：p2=1
    await hb._beat_once()  # 第 2 次 miss：p2>=threshold → suspect + 确认

    assert hb.is_suspect("p2")
    assert hb.is_dead("p2")
    status = hb.node_status()
    assert status["p2"]["state"] in ("suspect", "dead")


@pytest.mark.asyncio
async def test_confirm_dead_requires_majority():
    # 3 节点集群（self + p1 + p2）：多数派 = 2（含本节点自身观测一票）
    cfg = make_config(peers=["p1", "p2"])
    hb = PeerHeartbeat(config=cfg, node_id="me")

    # 无任何 peer 确认（仅自身 1 票 < 2）→ 不 dead
    hb.set_gossip_fn(lambda ep, about: False)
    assert await hb.confirm_dead("deadX") is False

    # 1 个 peer 确认（自身 + p1 共 2 票 == 多数派）→ dead
    hb.set_gossip_fn(lambda ep, about: ep == "p1")
    assert await hb.confirm_dead("deadX") is True


@pytest.mark.asyncio
async def test_on_dead_callback_fired_when_majority_confirmed():
    cfg = make_config(peers=["p1", "p2"])
    hb = PeerHeartbeat(config=cfg, node_id="me")
    hb.set_gossip_fn(lambda ep, about: True)
    fired = []
    hb.set_on_dead(lambda node: fired.append(node))

    assert await hb.confirm_dead("deadY") is True
    assert "deadY" in fired


@pytest.mark.asyncio
async def test_stop_broadcasts_leave():
    cfg = make_config(peers=["p1", "p2"])
    t = _DeadTransport("nope")
    hb = PeerHeartbeat(config=cfg, transport=t, node_id="me")
    await hb.start()
    await hb.stop()
    ops = [op for (ep, op) in t.calls if op == "leave"]
    assert len(ops) == 2  # 每个 seed 广播 leave