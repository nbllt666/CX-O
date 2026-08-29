"""PeerHeartbeat 测试：miss→suspect、多数派确认（自 mock 多数）、on_dead 回调、
观测键统一（H7）、投票去重（H7）、死亡节点复活通道（M3）、
gossip 问询并发化与死亡确认后台化（不阻塞 _beat_once）。"""
import asyncio
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
    await hb._beat_once()  # 第 2 次 miss：p2>=threshold → suspect + 确认（后台任务）

    # 确认流程已后台化：等待在途确认任务完成后断言终态
    if hb._confirm_tasks:
        await asyncio.gather(*list(hb._confirm_tasks))

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


# ---------------- gossip 问询并发化 + 死亡确认后台化 ----------------

@pytest.mark.asyncio
async def test_confirm_dead_asks_gossip_concurrently():
    """confirm_dead 并发问询全部 peer：mock _ask_gossip 统计最大并发数 == peer 数。

    旧实现串行 await（单 peer 超时最高 15s），修复后 gather 并发——
    所有问询应处于同时在途状态。
    """
    cfg = make_config(peers=["p1", "p2", "p3"])
    hb = PeerHeartbeat(config=cfg, node_id="me")

    inflight = {"n": 0, "max": 0}

    async def fake_ask(peer, about):
        inflight["n"] += 1
        inflight["max"] = max(inflight["max"], inflight["n"])
        await asyncio.sleep(0.02)  # 让出控制权，暴露并发窗口
        inflight["n"] -= 1
        return True

    hb._ask_gossip = fake_ask
    assert await hb.confirm_dead("deadZ") is True
    assert inflight["max"] == 3  # 3 个 peer 并发问询，而非串行 1


@pytest.mark.asyncio
async def test_confirm_dead_total_timeout_treats_all_as_abstained():
    """单轮 gossip 总超时：未应答的 peer 全部按弃权计票（不抛超时异常）。"""
    cfg = make_config(peers=["slow1", "slow2"])
    hb = PeerHeartbeat(config=cfg, node_id="me")

    async def hanging_ask(peer, about):
        await asyncio.sleep(30)  # 远超总超时，应被 wait_for 取消

    hb._ask_gossip = hanging_ask
    # 压缩总超时：transport 无 _timeout_sec 时默认 7.5 → 总超时 15s，太慢；
    # 注入小 _timeout_sec 验证超时路径（total = max(1, min(0.1*2, 15)) = 1s 下限，
    # 仍偏慢 → 直接改为 monkey transport 为带 _timeout_sec=0.1 的假对象）
    hb._transport = SimpleNamespace(_timeout_sec=0.1)

    import time as _t
    start = _t.monotonic()
    assert await hb.confirm_dead("deadT") is False  # 仅自身 1 票 < 多数派 2
    elapsed = _t.monotonic() - start
    assert elapsed < 5  # 总超时生效（未挂满 30s）
    assert set(hb.last_confirm_report["abstained"]) == {"slow1", "slow2"}


@pytest.mark.asyncio
async def test_confirm_runs_in_background_not_blocking_beat():
    """确认任务后台化：_beat_once 只发起不等待——确认未完成时主循环已返回。"""
    # 双 peer：p1 掉线成为确认目标（被排除出问询名单），p2 投赞成票
    cfg = make_config(peers=["p1", "p2"], miss_threshold=1)
    t = _DeadTransport("p1")
    hb = PeerHeartbeat(config=cfg, transport=t, node_id="me")
    release = asyncio.Event()

    async def slow_ask(peer, about):
        await release.wait()  # 阻塞确认直到测试放行
        return True

    hb._ask_gossip = slow_ask
    await hb._beat_once()  # p1 miss 达阈值 → 发起后台确认后立即返回

    assert "p1" in hb._confirm_inflight  # 在途登记（去重依据）
    assert not hb.is_dead("p1")          # 主循环未阻塞等待确认结果

    release.set()
    await asyncio.gather(*list(hb._confirm_tasks))  # 等待后台确认完成
    assert hb.is_dead("p1")              # 自身观测 + p2 赞成 = 多数派(2/3)


@pytest.mark.asyncio
async def test_confirm_task_dedup_per_node():
    """同一 node_id 确认在途时不再重复发起（第二轮 miss 达标不叠加问询）。"""
    # 双 peer：p1 掉线成为确认目标，p2 为问询对象
    cfg = make_config(peers=["p1", "p2"], miss_threshold=1)
    t = _DeadTransport("p1")
    hb = PeerHeartbeat(config=cfg, transport=t, node_id="me")
    calls = {"n": 0}
    gate = asyncio.Event()

    async def slow_ask(peer, about):
        calls["n"] += 1
        await gate.wait()
        return False

    hb._ask_gossip = slow_ask
    entered = asyncio.Event()

    async def slow_ask_enter(peer, about):
        entered.set()  # 记录"确认任务已真正进入问询"
        return await slow_ask(peer, about)

    hb._ask_gossip = slow_ask_enter
    await hb._beat_once()  # p1 miss（阈值 1）→ 发起确认
    # 确定性等待：确认任务穿透 create_task→wait_for→gather 层级进入 slow_ask
    await asyncio.wait_for(entered.wait(), timeout=2)
    await hb._beat_once()  # p1 再次 miss 达标 → 在途去重，不得再发起
    assert calls["n"] == 1

    gate.set()
    await asyncio.gather(*list(hb._confirm_tasks))
    assert "p1" not in hb._confirm_inflight  # 完成后在途标记释放


@pytest.mark.asyncio
async def test_stop_cancels_inflight_confirm_tasks():
    """stop 取消在途确认后台任务，且不触发 on_dead 接管回调。"""
    cfg = make_config(peers=["p1"], miss_threshold=1)
    t = _DeadTransport("p1")
    hb = PeerHeartbeat(config=cfg, transport=t, node_id="me")
    fired = []
    hb.set_on_dead(lambda node: fired.append(node))
    release = asyncio.Event()

    async def slow_ask(peer, about):
        await release.wait()
        return True

    hb._ask_gossip = slow_ask
    await hb._beat_once()
    assert hb._confirm_tasks  # 确认任务在途

    await hb.stop()
    assert not hb._confirm_tasks       # 在途任务已取消并清理
    assert fired == []                 # 未触发 on_dead 接管
    release.set()                      # 放行（协程已被取消，此信号无效果）