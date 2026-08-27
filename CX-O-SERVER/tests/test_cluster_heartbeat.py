"""PeerHeartbeat 测试：miss→suspect、多数派确认（自 mock 多数）、on_dead 回调、
观测键统一（H7）、投票去重（H7）、死亡节点复活通道（M3）。"""
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


# ---------------- H7: 观测键统一（endpoint→node_id 换算） ----------------

class _AllOkTransport:
    async def send(self, peer_endpoint, op, node_id, request_id, seq=0, epoch=0, payload=None):
        return True


@pytest.mark.asyncio
async def test_outbound_uses_node_id_key_after_binding():
    """H7：登记映射后，出站成功/失败均以 node_id 记账，入站心跳可互清同一键。"""
    cfg = make_config(peers=["ep-1"], miss_threshold=2)
    t = _DeadTransport("ep-1")
    hb = PeerHeartbeat(config=cfg, transport=t, node_id="me")
    hb.bind_endpoint_node("ep-1", "nid-1")

    await hb._beat_once()  # 失败 → miss 记在 "nid-1"
    assert hb._miss.get("nid-1") == 1
    assert "ep-1" not in hb._miss  # 不得再使用 endpoint 键

    # 入站心跳（真实场景：对端恢复后主动发来）→ 同一键被清零 + healthy
    hb.record_inbound_heartbeat("nid-1", {"role": "standby", "epoch": 0})
    assert "nid-1" not in hb._miss
    assert hb.node_status()["nid-1"]["state"] == "healthy"


def test_vote_observation_dedupes_same_peer_double_keys():
    """H7：同 peer 的 endpoint 键与 node_id 键只计一票。"""
    cfg = make_config(peers=["ep-1", "ep-2"])
    hb = PeerHeartbeat(config=cfg, node_id="me")
    hb.bind_endpoint_node("ep-1", "nid-1")
    hb._peer_state["ep-1"] = {"state": "healthy", "last_heartbeat": None}
    hb._peer_state["nid-1"] = {"state": "healthy", "last_heartbeat": None}  # 同一 peer 双键
    hb._peer_state["ep-2"] = {"state": "healthy", "last_heartbeat": None}

    assert hb.vote_observation() == 2  # nid-1 去重后算一个 + ep-2


@pytest.mark.asyncio
async def test_confirm_dead_skips_target_resolved_via_mapping():
    """H7：被确认对象经映射解析后，不向其自身问询死亡意见（其余 peer 正常计票）。"""
    cfg = make_config(peers=["victim-ep", "witness-ep"])
    asked = []

    def gossip(ep, about):
        asked.append((ep, about))
        return ep == "witness-ep"

    hb = PeerHeartbeat(config=cfg, node_id="me")
    hb.set_gossip_fn(gossip)
    hb.bind_endpoint_node("victim-ep", "victim-nid")

    # 自身 + witness 两票 >= 多数派(2/3+1=2)：映射解析使 victim 不自证死亡
    assert await hb.confirm_dead("victim-nid") is True
    assert "victim-ep" not in [ep for ep, _ in asked]
    assert ("witness-ep", "victim-nid") in asked


# ---------------- M3: 死亡节点复活通道 ----------------

@pytest.mark.asyncio
async def test_dead_node_recovered_by_successful_beat(tmp_path, caplog):
    """M3：死亡节点心跳重新成功 → 清理 dead/suspect 并留 RECOVERED 审计日志。"""
    import logging

    cfg = make_config(peers=["p1"], miss_threshold=2)
    t = _DeadTransport("p1")
    hb = PeerHeartbeat(config=cfg, transport=t, node_id="me")
    hb.set_gossip_fn(lambda ep, about: True)
    hb._dead.add("p1")
    hb._peer_state["p1"] = {"state": "dead", "last_heartbeat": None}

    t.dead_peer = "__none__"  # 对端"复活"：此后心跳成功
    with caplog.at_level(logging.WARNING, logger="server.core.cluster.heartbeat"):
        await hb._beat_once()
    assert not hb.is_dead("p1")
    assert not hb.is_suspect("p1")
    assert hb.node_status()["p1"]["state"] == "healthy"
    assert any("RECOVERED" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_dead_node_recovered_by_inbound_heartbeat(caplog):
    """M3：死亡节点入站心跳即复活证据 → 状态自然恢复。"""
    import logging

    cfg = make_config(peers=[], miss_threshold=2)
    hb = PeerHeartbeat(config=cfg, node_id="me")
    hb._dead.add("risen-node")
    hb._miss["risen-node"] = 9
    with caplog.at_level(logging.WARNING, logger="server.core.cluster.heartbeat"):
        st = hb.record_inbound_heartbeat("risen-node", {"role": "standby"})
    assert st["state"] == "healthy"
    assert not hb.is_dead("risen-node")
    assert "risen-node" not in hb._miss
    assert any("RECOVERED" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_status_for_resolves_via_mapping():
    """H7 配套：topology 按 endpoint 查询时可经映射命中 node_id 键状态。"""
    cfg = make_config(peers=["ep-9"])
    hb = PeerHeartbeat(config=cfg, node_id="me")
    hb.bind_endpoint_node("ep-9", "nid-9")
    hb._peer_state["nid-9"] = {"state": "suspect", "last_heartbeat": "T"}
    st = hb.status_for("ep-9")
    assert st["state"] == "suspect"
    assert hb.status_for("unknown-ep") is None