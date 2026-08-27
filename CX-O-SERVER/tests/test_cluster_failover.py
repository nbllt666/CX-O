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


# ---------------- M4: 并发串行化 + 成功回调 ----------------

@pytest.mark.asyncio
async def test_concurrent_takeover_serialized_by_instance_lock():
    """M4：并发 maybe_takeover 经实例锁串行——前序完全落定后后序才评估，
    全程无交错的角色/纪元撕裂。"""
    cfg = make_config(["p1", "p2"])
    consensus = ConsensusGuard(config=cfg, vote_source=lambda: 2)
    failover = FailoverManager(config=cfg, consensus=consensus, node_id="me", current_epoch=0)

    async def slow_adopt(from_node_id):
        # 替换真实 adopt：保留"记录继承来源"语义，仅拉长临界区放大并发窗口
        failover.inherited_from = from_node_id
        import asyncio as _aio
        await _aio.sleep(0.01)

    failover.adopt_inheritance = slow_adopt  # type: ignore[method-assign]

    results = await __import__("asyncio").gather(
        failover.maybe_takeover("deadA"),
        failover.maybe_takeover("deadA"),
    )
    assert all(r["took_over"] for r in results)
    epochs = sorted(r["epoch"] for r in results)
    assert epochs == [1, 2]          # 串行递增，而非交错产生相同/跳变纪元
    assert failover.role == "active"
    assert failover.epoch == 2
    assert failover.inherited_from == "deadA"


@pytest.mark.asyncio
async def test_on_takeover_callback_invoked_with_final_state():
    """M4：接管成功触发回调，SentinelCluster 借此回写 role/epoch/inherited_from。"""
    cfg = make_config(["p1", "p2"])
    consensus = ConsensusGuard(config=cfg, vote_source=lambda: 2)
    failover = FailoverManager(config=cfg, consensus=consensus, node_id="me", current_epoch=0)
    seen_default = {"role": "standby", "epoch": 0, "inherited_from": None}

    def _manager_backfill(role, epoch, inherited):
        seen_default.update(role=role, epoch=epoch, inherited_from=inherited)

    failover.set_on_takeover(_manager_backfill)
    result = await failover.maybe_takeover("deadNode")
    assert result["took_over"] is True
    assert seen_default == {"role": "active", "epoch": 1, "inherited_from": "deadNode"}


# ---------------- M6: state_source 异常 → rejected（保守安全） ----------------

@pytest.mark.asyncio
async def test_state_source_exception_returns_rejected_not_dirty_bypass():
    """M6：state_source 抛异常视为仲裁失败→rejected；不得以兜底 (0,0) 旁路脏接管红线。"""
    cfg = make_config(["p1", "p2"])
    consensus = ConsensusGuard(config=cfg, vote_source=lambda: 2)
    events = []
    failover = FailoverManager(config=cfg, consensus=consensus, node_id="me", current_epoch=5)
    failover.set_event_source(lambda topic, data: events.append((topic, data)))

    def broken_state_source(dead):
        raise RuntimeError("state db unavailable")

    failover.set_state_source(broken_state_source)

    result = await failover.maybe_takeover("deadNode")
    assert result["took_over"] is False
    from server.core.cluster._common import CLUSTER_SERVICE_ERROR
    assert result["error_code"] == CLUSTER_SERVICE_ERROR
    assert failover.role == "standby"      # 复位
    assert failover.epoch == 5             # 异常路径同样不消耗纪元
    topics = [t for (t, _) in events]
    assert "failover_started" in topics
    started = [d for (t, d) in events if t == "failover_started"][0]
    assert started["decision"] == "rejected"
    assert started["reason"] == "CLUSTER_STATE_SOURCE_ERROR"


@pytest.mark.asyncio
async def test_state_source_explicit_zero_tuple_still_normal_path():
    """M6 区分口径：显式返回 (0, 0) 属正常路径（如冷启动无状态），照常走仲裁。"""
    cfg = make_config(["p1", "p2"], role="standby")
    consensus = ConsensusGuard(config=cfg, vote_source=lambda: 2)
    failover = FailoverManager(config=cfg, consensus=consensus, node_id="me", current_epoch=0)
    failover.set_state_source(lambda dead: (0, 0))  # min=0：非脏接管

    result = await failover.maybe_takeover("coldStart")
    assert result["took_over"] is True
    assert result["epoch"] == 1