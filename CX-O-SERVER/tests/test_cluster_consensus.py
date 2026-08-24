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