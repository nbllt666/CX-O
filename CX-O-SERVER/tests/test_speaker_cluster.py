"""在线说话人聚类模块 pytest 单元测试（对应 AC Spec Task 2 + 测试 8.1）。

运行前需保证 asr_container 可导入：测试位于 CX-O-SERVER 目录，sys.path 已含工程根；
此处显式把工程根（CX-O-SERVER）加入 sys.path，兼容从任意目录执行 pytest 的场景。
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

# 确保 asr_container 可导入
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from asr_container.speaker_cluster import SpeakerClusterer  # noqa: E402

DIM = 192


def _norm(vec: np.ndarray) -> np.ndarray:
    return vec / np.linalg.norm(vec)


@pytest.fixture(scope="module")
def orthogonal():
    """一批两两正交的 192 维单位向量，便于精确控制余弦相似度阈值。"""
    A = np.zeros(DIM)
    A[0] = 1.0
    B = np.zeros(DIM)
    B[1] = 1.0
    C = np.zeros(DIM)
    C[2] = 1.0
    return [_norm(A), _norm(B), _norm(C)]


def test_case1_registered_high_similarity(orthogonal):
    """注册 profile "A"，对其向量加微小噪声分类应归属 "A" 且 conf>=阈值。"""
    vA = orthogonal[0]
    clusterer = SpeakerClusterer(threshold=0.65)
    assert clusterer.upsert_profiles([{"name": "A", "embeddings": vA.tolist()}]) == 1
    s = clusterer.create_session()
    sid, registered, conf = s.classify(vA + 0.001)
    assert sid == "A"
    assert registered is True
    assert conf >= 0.65


def test_case2_unregistered_session_ids(orthogonal):
    """未注册向量建临时簇；编号会话内稳定、不同方向编号递增。"""
    vB, vC = orthogonal[1], orthogonal[2]
    clusterer = SpeakerClusterer(threshold=0.65)
    s = clusterer.create_session()

    sid0, reg0, conf0 = s.classify(vB)
    assert sid0 == "spk_0"
    assert reg0 is False
    assert conf0 < 0.65

    sid0b, _, _ = s.classify(vB)  # 再分类同向量仍命中 spk_0
    assert sid0b == "spk_0"

    sid1, _, _ = s.classify(vC)  # 另一个方向走行新簇
    assert sid1 == "spk_1"


def test_case3_rolling_update_convergence(orthogonal):
    """同会话滚动更新：多次归簇后用高相似偏向量，conf 应随质心收敛而上升。"""
    vB = orthogonal[1]
    basis = np.zeros(DIM)
    basis[3] = 0.02
    clusterer = SpeakerClusterer(threshold=0.65)
    s = clusterer.create_session()
    s.classify(vB)  # 建立 spk_0

    lvl = []
    for _ in range(3):
        e = _norm(vB + 0.08 * basis)  # 略偏离 vB，但仍归 spk_0
        _, _, conf = s.classify(e)
        lvl.append(conf)
    # 质心向若干偏离向量滚动收敛后，相近向量的相似度应一路走高
    assert lvl[-1] > lvl[0]


def test_case4_session_isolation(orthogonal):
    """两个 session 独立：s1 的 spk_0 不影响 s2，s2 首个未知仍是 spk_0。"""
    vB, vC = orthogonal[1], orthogonal[2]
    clusterer = SpeakerClusterer(threshold=0.65)
    s1 = clusterer.create_session()
    s2 = clusterer.create_session()

    s1.classify(vB)  # s1 造出 spk_0
    sid, _, _ = s1.classify(vC)
    assert sid == "spk_1"

    sid2, _, _ = s2.classify(vC)  # s2 首个未知仍是 spk_0
    assert sid2 == "spk_0"


def test_case5_reset_resets_counter(orthogonal):
    """reset() 后编号归零。"""
    vB, vC = orthogonal[1], orthogonal[2]
    clusterer = SpeakerClusterer(threshold=0.65)
    s = clusterer.create_session()
    s.classify(vB)
    s.classify(vC)
    s.classify(orthogonal[0])
    s.reset()
    assert s.classify(vB)[0] == "spk_0"


def test_case6_upsert_full_replace(orthogonal):
    """upsert_profiles 全量替换：旧的 profile 向量被新的质心取代。"""
    vA = orthogonal[0]
    clusterer = SpeakerClusterer(threshold=0.65)
    clusterer.upsert_profiles([{"name": "A", "embeddings": vA.tolist()}])
    s = clusterer.create_session()
    assert s.classify(vA + 0.001)[0] == "A"  # 旧质心成立

    # 全量替换 A 的新质心（方向 B），旧向量 A 不再命中 A，而是入临时簇
    clusterer.upsert_profiles([{"name": "A", "embeddings": orthogonal[1].tolist()}])
    s2 = clusterer.create_session()
    sid, reg, _ = s2.classify(vA)
    assert sid == "spk_0"
    assert reg is False


def test_case7_picks_higher_similarity(orthogonal):
    """多注册 profile 时正确选择相似度较高者。"""
    vA = orthogonal[0]
    clusterer = SpeakerClusterer(threshold=0.9)
    clusterer.upsert_profiles([
        {"name": "A", "embeddings": vA.tolist()},
        {"name": "B", "embeddings": orthogonal[2].tolist()},
    ])
    s = clusterer.create_session()
    # 叠加 vA 肩部小量，使其与 A 质心相似度最高
    nearA = _norm(vA + 0.01 * orthogonal[1])
    sid, reg, _ = s.classify(nearA)
    assert sid == "A"
    assert reg is True


def test_clear_profiles(orthogonal):
    """clear_profiles 清空注册池，之后未知向量走临时簇。"""
    vA = orthogonal[0]
    clusterer = SpeakerClusterer(threshold=0.65)
    clusterer.upsert_profiles([{"name": "A", "embeddings": vA.tolist()}])
    clusterer.clear_profiles()
    assert clusterer.profile_count() == 0
    assert clusterer.profile_names() == []
    s = clusterer.create_session()
    assert s.classify(vA)[0] == "spk_0"


def test_recent_match_none_and_reset(orthogonal):
    """未 classify 时 recent_match 返回 None；reset 后同样清空。"""
    vB = orthogonal[1]
    clusterer = SpeakerClusterer(threshold=0.65)
    s = clusterer.create_session()
    assert s.recent_match() is None  # 尚未 classify
    s.classify(vB)
    assert s.recent_match() is not None
    s.reset()
    assert s.recent_match() is None


def test_recent_match_registered_pool(orthogonal):
    """命中注册池时记录最近命中为注册名字 + 注册质心 embedding。"""
    vA = orthogonal[0]
    clusterer = SpeakerClusterer(threshold=0.65)
    clusterer.upsert_profiles([{"name": "A", "embeddings": vA.tolist()}])
    s = clusterer.create_session()
    sid, reg, _ = s.classify(vA + 0.001)
    assert sid == "A"
    assert reg is True
    m = s.recent_match()
    assert m is not None
    cid, centroid = m
    assert cid == "A"
    assert isinstance(centroid, list)
    assert len(centroid) == DIM


def test_recent_match_temp_cluster(orthogonal):
    """多次命中临时簇滚动更新质心后，recent_match 记录 spk_{n} 与最新质心。"""
    vB = orthogonal[1]
    clusterer = SpeakerClusterer(threshold=0.65)
    s = clusterer.create_session()
    s.classify(vB)        # 新建 spk_0
    s.classify(vB)        # 命中临时簇，滚动更新质心
    m = s.recent_match()
    assert m is not None
    cid, centroid = m
    assert cid == "spk_0"
    assert isinstance(centroid, list)
    assert len(centroid) == DIM


def test_recent_match_new_cluster(orthogonal):
    """首次未注册向量新建临时簇时，recent_match 记录 spk_{n} 与原始 embedding 克隆。"""
    vC = orthogonal[2]
    clusterer = SpeakerClusterer(threshold=0.65)
    s = clusterer.create_session()
    s.classify(vC)
    m = s.recent_match()
    assert m is not None
    cid, centroid = m
    assert cid == "spk_0"
    assert isinstance(centroid, list)
    assert len(centroid) == DIM