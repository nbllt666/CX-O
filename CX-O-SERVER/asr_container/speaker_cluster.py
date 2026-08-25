"""在线说话人聚类模块（纯逻辑，无外部依赖）。

设计说明：
  本模块为 ASR 容器引擎提供「在线说话人聚类」能力，采用纯 numpy 实现，
  有意不依赖 funasr / torch，便于在宿主环境做纯逻辑单元测试与容器内复用。

聚类模型：
  - 特征：192 维说话人 embedding，相似度用余弦相似度度量（先 L2 归一化再求点积）。
  - 说话人长期画像来自服务端权威推送（upsert_profiles 全量替换），每个注册说话人
    以其所有 embedding 的「归一化质心」为代表向量；同一说话人的嵌入只聚合一次（去重）。
  - 每个连接 / 会话（SpeakerSession）持有自己的临时簇：用于对「尚未注册」的说话人
    做在线增量聚类，新号 spk_{n} 从 0 递增且会话内不复用。
  - 判定时把「注册质心」与「会话临时簇质心」合并为候选集，取余弦相似度最高者：
    命中注册质心 → registered=True；命中临时簇 → registered=False（保留临时身份）。
    最高相似度低于阈值则新建临时簇并返回该相似度作为置信度。

会话隔离：
  - 不同会话的 spk_N 编号相互独立、互不影响已由各自会话实例的状态隔离保证。
  - upsert_profiles 后新会话即刻使用新质心（全量替换语义）。
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

import numpy as np

__all__ = ["SpeakerClusterer", "SpeakerSession"]


def _l2_normalize(vec: np.ndarray) -> np.ndarray:
    """对一维向量做 L2 归一化；零向量时保持原位（静默退化，避免除零）。"""
    norm = np.linalg.norm(vec)
    if norm > 0:
        return vec / norm
    return vec


def _to_vector(embedding: Sequence[float], dim: int) -> np.ndarray:
    """将 list / np.ndarray 输入的 embedding 转换为 (dim,) 的 float64 向量。"""
    vec = np.asarray(embedding, dtype=np.float64).reshape(-1)
    if vec.shape[0] != dim:
        raise ValueError(f"embedding 维度 {vec.shape[0]} 与期望维度 {dim} 不符")
    return vec


class SpeakerSession:
    """会话级临时簇实例：在同一注册池下维护独立的说话人增量聚类状态。"""

    def __init__(self, clusterer: "SpeakerClusterer") -> None:
        self._clusterer = clusterer
        self._clusters: List[np.ndarray] = []   # 临时簇质心（已 L2 归一化）
        self._counts: List[int] = []            # 临时簇累计归一化 embedding 条数
        self._next_id: int = 0                  # 下一个临时簇编号（会话内不复用）
        self._last_match: Optional[list] = None  # 最近命中 [cluster_id, 质心 ndarray]

    def classify(self, embedding) -> Tuple[str, bool, float]:
        """对单个 embedding 分类。

        输入：192 维向量（list 或 np.ndarray）。
        返回：(speaker_id, registered, conf)。
          - registered=True  → speaker_id 为注册说话人名；
          - registered=False → speaker_id 为会话内临时编号 spk_{n}。
          - conf 为本次判定命中的最大余弦相似度（新建临时簇时即该最大相似度）。
        """
        e = _l2_normalize(_to_vector(embedding, self._clusterer._dim))

        # 候选集：注册质心 + 会话临时簇质心
        centroids = self._clusterer._centroids + self._clusters
        registered_mask = [True] * len(self._clusterer._centroids) + [False] * len(self._clusters)

        if centroids:
            dots = np.array([float(np.dot(e, c)) for c in centroids], dtype=np.float64)
            idx = int(np.argmax(dots))
            conf = float(dots[idx])
        else:
            idx = -1
            conf = 0.0

        if conf >= self._clusterer.threshold:
            if registered_mask[idx]:
                name = self._clusterer._profile_names[idx]
                self._last_match = [name, self._clusterer._centroids[idx]]
                return name, True, conf
            # 命中临时簇：滚动更新质心与 count
            c_idx = idx - len(self._clusterer._centroids)
            count = self._counts[c_idx]
            new_centroid = _l2_normalize((self._clusters[c_idx] * count + e) / float(count + 1))
            self._clusters[c_idx] = new_centroid
            self._counts[c_idx] = count + 1
            self._last_match = [f"spk_{c_idx}", new_centroid.copy()]  # 克隆，防后续质心变动影响
            return f"spk_{c_idx}", False, conf

        # 新建临时簇
        spk_id = f"spk_{self._next_id}"
        self._clusters.append(e)
        self._counts.append(1)
        self._next_id += 1
        self._last_match = [spk_id, e]
        return spk_id, False, conf

    def recent_match(self) -> Optional[Tuple[str, List[float]]]:
        """返回最近命中簇的 (cluster_id, 质心 embedding)。未 classify 时返回 None。"""
        if self._last_match is None:
            return None
        return (self._last_match[0], np.asarray(self._last_match[1], dtype=np.float64).tolist())

    def reset(self) -> None:
        """清空临时簇与 next_id（连接断开 / 换人时调用）。"""
        self._clusters.clear()
        self._counts.clear()
        self._next_id = 0
        self._last_match = None


class SpeakerClusterer:
    """说话人在线聚类器：管理服务端权威注册画像池，并派生会话级聚类实例。"""

    def __init__(self, threshold: float = 0.65, dim: int = 192) -> None:
        self.threshold = float(threshold)
        self._dim = int(dim)
        self._profiles: List[dict] = []
        self._profile_names: List[str] = []
        self._centroids: List[np.ndarray] = []  # 各注册说话人的归一化质心（已去重合并）

    def _merge_embeddings(self, emb: object) -> Optional[np.ndarray]:
        """将 profile 的 embeddings 聚合成一个归一化质心；无有效数据时返回 None。

        输入支持两种形态：单条 [float]x192，或多条 [[float]x192, ...]。
        """
        try:
            arr = np.asarray(emb, dtype=np.float64)
        except (TypeError, ValueError):
            return None
        if arr.ndim == 1:
            if arr.shape[0] != self._dim:
                return None
            entries = [arr]
        elif arr.ndim == 2:
            entries = [row for row in arr if row.shape[0] == self._dim]
        else:
            return None
        if not entries:
            return None
        # 去重（同向量）后取「各 L2 归一化向量的均值」，再 L2 归一化为质心
        normed = [_l2_normalize(v) for v in entries]
        matrix = np.vstack(normed)
        unique = np.unique(matrix, axis=0)
        mean = unique.mean(axis=0)
        return _l2_normalize(mean)

    def upsert_profiles(self, profiles: List[dict]) -> int:
        """全量替换注册 profiles（服务端权威全量推送）。

        profile 形如 {"name": str, "embeddings": [[float]x192, ...]} 或 {"name": str, "embeddings": [float]x192}。
        返回注册 profiles 数量。
        """
        self._profiles = list(profiles)
        self._profile_names = []
        self._centroids = []
        for p in self._profiles:
            name = str(p.get("name"))
            centroid = self._merge_embeddings(p.get("embeddings"))
            if centroid is None:
                continue
            self._profile_names.append(name)
            self._centroids.append(centroid)
        return len(self._profiles)

    def clear_profiles(self) -> None:
        """清空注册 profiles（供 delete 全量同步用）。"""
        self._profiles = []
        self._profile_names = []
        self._centroids = []

    def create_session(self) -> SpeakerSession:
        """返回会话级临时簇实例（同一注册池下的独立说话人状态）。"""
        return SpeakerSession(self)

    def profile_names(self) -> List[str]:
        """返回当前注册说话人名称列表。"""
        return list(self._profile_names)

    def profile_count(self) -> int:
        """返回当前有效注册说话人数量。"""
        return len(self._profiles)


def _demo() -> None:
    """简单自检示例（非测试，仅供手动验证契约行为）。"""
    rng = np.random.default_rng(0)
    vA = _l2_normalize(rng.standard_normal(192))
    vB = _l2_normalize(rng.standard_normal(192))
    clusterer = SpeakerClusterer()
    n = clusterer.upsert_profiles([{"name": "A", "embeddings": vA.tolist()}])
    assert n == 1
    s = clusterer.create_session()
    print("A ->", s.classify(vA + 0.001))
    print("vB ->", s.classify(vB))
    s.reset()
    print("reset OK")


if __name__ == "__main__":
    _demo()