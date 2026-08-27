"""ConsensusGuard 测试：脏接管 / 无多数 / 见证仲裁 / 防双主。"""
from types import SimpleNamespace

import pytest

from server.core.cluster.consensus import ConsensusGuard
from server.core.cluster._common import (
    CLUSTER_DIRTY_TAKEOVER,
    CLUSTER_NO_QUORUM,
    CLUSTER_SPLIT_BRAIN_RISK,
    ClusterDirtyTakeoverError,
    ClusterNoQuorumError,
    ClusterSplitBrainRiskError,
)


def make_witness(endpoint):
    return SimpleNamespace(endpoint=endpoint, secret="")


def make_config(peers=(), witness_endpoint=""):
    return SimpleNamespace(peers=list(peers), witness=make_witness(witness_endpoint))


def test_dirty_takeover_rejected():
    c = ConsensusGuard(config=make_config(["p1", "p2"]))
    with pytest.raises(ClusterDirtyTakeoverError) as exc:
        c.can_takeover("p3", candidate_state_version=3, min_version=10, epoch=1)
    assert exc.value.error_code == CLUSTER_DIRTY_TAKEOVER


def test_no_quorum_when_votes_below_majority():
    c = ConsensusGuard(config=make_config(["p1", "p2"]), vote_source=lambda: 1)
    with pytest.raises(ClusterNoQuorumError) as exc:
        c.can_takeover("p3", candidate_state_version=20, min_version=1, epoch=1)
    assert exc.value.error_code == CLUSTER_NO_QUORUM


def test_majority_passes():
    c = ConsensusGuard(config=make_config(["p1", "p2"]), vote_source=lambda: 2)
    assert c.can_takeover("p3", candidate_state_version=20, min_version=1, epoch=1) is True
    assert c.current_epoch == 1


def test_two_node_without_witness_no_quorum():
    c = ConsensusGuard(config=make_config(["p1"], witness_endpoint=""))
    with pytest.raises(ClusterNoQuorumError) as exc:
        c.can_takeover("p2", candidate_state_version=5, min_version=1, epoch=1)
    assert exc.value.error_code == CLUSTER_NO_QUORUM


def test_two_node_passes_with_witness():
    c = ConsensusGuard(config=make_config(["p1"], witness_endpoint="w:1"))
    assert c.can_takeover("p2", candidate_state_version=5, min_version=1, epoch=1) is True


def test_epoch_not_highest_split_brain_risk():
    c = ConsensusGuard(config=make_config(["p1", "p2"]), vote_source=lambda: 2, current_epoch=2)
    with pytest.raises(ClusterSplitBrainRiskError) as exc:
        c.can_takeover("p3", candidate_state_version=5, min_version=1, epoch=2)
    assert exc.value.error_code == CLUSTER_SPLIT_BRAIN_RISK
    # H6：失败路径不得推进内部纪元
    assert c.current_epoch == 2


def test_no_quorum_failure_does_not_commit_epoch_and_retry_recovers():
    """H6 回归：quorum 判定失败后 _current_epoch 不得被提前提交。

    此前实现先写 _current_epoch 再判 quorum，NoQuorum 异常后同参数重试
    被误判为 epoch 不升 → SplitBrainRisk 永久卡死。两阶段判定后应可恢复。
    """
    votes = {"n": 0}

    def flaky_vote_source():
        votes["n"] += 1
        return 1 if votes["n"] == 1 else 2  # 首次不足多数，第二次达标

    c = ConsensusGuard(config=make_config(["p1", "p2"]), vote_source=flaky_vote_source)
    with pytest.raises(ClusterNoQuorumError):
        c.can_takeover("p3", candidate_state_version=20, min_version=1, epoch=5)
    assert c.current_epoch != 5  # 失败未提交纪元

    # 同参数重试（对端票数恢复）应成功，而非误判脑裂
    assert c.can_takeover("p3", candidate_state_version=20, min_version=1, epoch=5) is True
    assert c.current_epoch == 5


def test_two_node_witness_failure_does_not_commit_epoch():
    """H6：2 节点无 witness 的 NoQuorum 失败同样不得提交纪元。"""
    c = ConsensusGuard(config=make_config(["p1"], witness_endpoint=""))
    with pytest.raises(ClusterNoQuorumError):
        c.can_takeover("p2", candidate_state_version=5, min_version=1, epoch=7)
    assert c.current_epoch == 0


def test_witness_arbitration():
    c = ConsensusGuard(config=make_config(["p1"], witness_endpoint="w:1"))
    candidates = [{"node_id": "a", "endpoint": "a:1"}, {"node_id": "b", "endpoint": "b:1"}]
    chosen = c.choose_leader_by_witness(candidates)
    assert chosen in ("a", "b")  # 默认取第一个（或与 witness 一致的端点）

    # 注入仲裁器：固定选 b
    c.set_witness_decider(lambda cands: "b")
    assert c.choose_leader_by_witness(candidates) == "b"


def test_witness_arbitration_without_witness_raises():
    c = ConsensusGuard(config=make_config(["p1"], witness_endpoint=""))
    with pytest.raises(ClusterNoQuorumError):
        c.choose_leader_by_witness([{"node_id": "a"}])