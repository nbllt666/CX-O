"""FailoverManager 测试：脏接管拒绝 / 无多数拒绝 / 成功接管 / 事件广播。"""
from types import SimpleNamespace

import pytest

from server.core.cluster.failover import FailoverManager
from server.core.cluster.consensus import ConsensusGuard
from server.core.cluster._common import CLUSTER_DIRTY_TAKEOVER, CLUSTER_NO_QUORUM


def make_witness(endpoint=""):
    return SimpleNamespace(endpoint=endpoint, secret="")


def make_config(peers, role="standby"):
    return SimpleNamespace(peers=list(peers), role=role, witness=make_witness())


@pytest.mark.asyncio
async def test_dirty_takeover_rejected_and_records_error():
    cfg = make_config(["p1", "p2"])  # 3 节点，多数派可达
    consensus = ConsensusGuard(config=cfg, vote_source=lambda: 2)
    events = []
    failover = FailoverManager(config=cfg, consensus=consensus, node_id="me", current_epoch=0)
    failover.set_event_source(lambda topic, data: events.append((topic, data)))
    failover.set_state_source(lambda dead: (3, 10))  # candidate 3 < min 10

    result = await failover.maybe_takeover("deadNode")
    assert result["took_over"] is False
    assert result["error_code"] == CLUSTER_DIRTY_TAKEOVER
    assert failover.role == "standby"  # 拒绝后复位
    # 仲裁失败不消耗 epoch：拒绝后仍为初始纪元，保证后续重试可用
    assert failover.epoch == 0
    assert result["epoch"] == 0
    topics = [t for (t, _) in events]
    assert "failover_started" in topics


@pytest.mark.asyncio
async def test_no_quorum_rejected():
    cfg = make_config(["p1", "p2"])
    consensus = ConsensusGuard(config=cfg, vote_source=lambda: 1)  # 少于一票
    failover = FailoverManager(config=cfg, consensus=consensus, node_id="me")
    failover.set_state_source(lambda dead: (20, 1))

    result = await failover.maybe_takeover("deadNode")
    assert result["took_over"] is False
    assert result["error_code"] == CLUSTER_NO_QUORUM


@pytest.mark.asyncio
async def test_successful_takeover_promotes_active_and_emits_events():
    cfg = make_config(["p1", "p2"], role="standby")
    consensus = ConsensusGuard(config=cfg, vote_source=lambda: 2)
    events = []
    failover = FailoverManager(config=cfg, consensus=consensus, node_id="me", current_epoch=0)
    failover.set_event_source(lambda topic, data: events.append((topic, data)))
    failover.set_state_source(lambda dead: (20, 5))

    result = await failover.maybe_takeover("deadNode")
    assert result["took_over"] is True
    assert result["role"] == "active"
    assert result["epoch"] == 1
    assert result["inherited_from"] == "deadNode"
    assert failover.role == "active"
    assert failover.inherited_from == "deadNode"
    # 保持自身 identity
    assert result["node_id"] == "me"

    topics = [t for (t, _) in events]
    assert "failover_started" in topics
    assert "failover_completed" in topics


@pytest.mark.asyncio
async def test_adopt_inheritance_keeps_own_identity():
    cfg = make_config(["p1"], role="standby")
    failover = FailoverManager(config=cfg, consensus=ConsensusGuard(config=cfg), node_id="me")
    await failover.adopt_inheritance("oldNode")
    assert failover.inherited_from == "oldNode"
    assert failover._node_id == "me"  # 不替换自身身份