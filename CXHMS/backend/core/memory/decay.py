import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class DecayParams:
    alpha: float
    lambda1: float
    lambda2: float
    min_score: float
    permanent: bool


@dataclass
class ImportanceLevel:
    score_range: Tuple[float, float]
    decay_type: str
    params: Dict
    permanent: bool
    retention_180d: float


class DecayCalculator:
    IMPORTANCE_LEVELS = {
        1.0: ImportanceLevel(
            score_range=(1.0, 1.0),
            decay_type="zero",
            params={"alpha": 0.0, "lambda1": 0.0, "lambda2": 0.0},
            permanent=True,
            retention_180d=1.0,
        ),
        0.92: ImportanceLevel(
            score_range=(0.85, 0.99),
            decay_type="exponential",
            params={"alpha": 0.2, "lambda1": 0.01, "lambda2": 0.001},
            permanent=False,
            retention_180d=0.95,
        ),
        0.77: ImportanceLevel(
            score_range=(0.70, 0.84),
            decay_type="exponential",
            params={"alpha": 0.35, "lambda1": 0.08, "lambda2": 0.015},
            permanent=False,
            retention_180d=0.80,
        ),
        0.60: ImportanceLevel(
            score_range=(0.50, 0.69),
            decay_type="exponential",
            params={"alpha": 0.6, "lambda1": 0.25, "lambda2": 0.04},
            permanent=False,
            retention_180d=0.50,
        ),
        0.40: ImportanceLevel(
            score_range=(0.30, 0.49),
            decay_type="exponential",
            params={"alpha": 0.75, "lambda1": 0.45, "lambda2": 0.08},
            permanent=False,
            retention_180d=0.25,
        ),
        0.15: ImportanceLevel(
            score_range=(0.0, 0.29),
            decay_type="exponential",
            params={"alpha": 0.9, "lambda1": 0.8, "lambda2": 0.15},
            permanent=False,
            retention_180d=0.05,
        ),
    }

    def __init__(self):
        self.current_time = datetime.now()

    def set_current_time(self, time: datetime):
        self.current_time = time

    def get_level_from_importance(self, importance: float) -> ImportanceLevel:
        if importance >= 0.95:
            return self.IMPORTANCE_LEVELS[1.0]
        elif importance >= 0.85:
            return self.IMPORTANCE_LEVELS[0.92]
        elif importance >= 0.70:
            return self.IMPORTANCE_LEVELS[0.77]
        elif importance >= 0.50:
            return self.IMPORTANCE_LEVELS[0.60]
        elif importance >= 0.30:
            return self.IMPORTANCE_LEVELS[0.40]
        else:
            return self.IMPORTANCE_LEVELS[0.15]

    def calculate_days_elapsed(self, created_at: str) -> float:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            delta = self.current_time - created
            return delta.total_seconds() / 86400.0
        except Exception as e:
            logger.error(f"计算时间差失败: {e}")
            return 0.0

    def calculate_exponential_decay(
        self,
        importance: float,
        days_elapsed: float,
        alpha: float = 0.6,
        lambda1: float = 0.25,
        lambda2: float = 0.04,
    ) -> float:
        """
        双阶段指数衰减函数（主模型默认）

        T(t) = α·e^(-λ₁·Δt) + (1-α)·e^(-λ₂·Δt)

        Args:
            importance: 初始重要性分数
            days_elapsed: 经过的天数
            alpha: 近期记忆权重系数
            lambda1: 快速衰减系数
            lambda2: 慢速衰减系数

        Returns:
            衰减后的分数
        """
        if days_elapsed <= 0:
            return importance

        decay_factor = alpha * math.exp(-lambda1 * days_elapsed) + (1 - alpha) * math.exp(
            -lambda2 * days_elapsed
        )

        return min(importance * decay_factor, 1.0)

    def calculate_ebbinghaus_decay(
        self, importance: float, days_elapsed: float, t50: float = 30.0, k: float = 2.0
    ) -> float:
        """
        艾宾浩斯优化版衰减函数（备选模型）

        T(t) = 1 / (1 + (Δt/T₅₀)^k)

        Args:
            importance: 初始重要性分数
            days_elapsed: 经过的天数
            t50: 衰减到50%所需时间（天）
            k: 曲线陡峭度参数

        Returns:
            衰减后的分数
        """
        if days_elapsed <= 0:
            return importance

        if t50 <= 0:
            return importance

        decay_factor = 1.0 / (1.0 + (days_elapsed / t50) ** k)

        return min(importance * decay_factor, 1.0)

    def calculate_permanent_decay(self, importance: float) -> float:
        return 1.0

    def calculate_decay(
        self,
        importance: float,
        created_at: str,
        decay_type: str = "exponential",
        decay_params: Optional[Dict] = None,
        permanent: bool = False,
    ) -> float:
        days_elapsed = self.calculate_days_elapsed(created_at)

        if decay_type == "zero" or importance >= 0.95 or permanent:
            return self.calculate_permanent_decay(importance)

        # 艾宾浩斯优化版衰减（实验性功能）
        if decay_type == "ebbinghaus":
            return self.calculate_ebbinghaus_decay(
                importance=importance,
                days_elapsed=days_elapsed,
                t50=decay_params.get("t50", 30.0) if decay_params else 30.0,
                k=decay_params.get("k", 2.0) if decay_params else 2.0,
            )

        # 双阶段指数衰减（默认）
        if decay_params:
            return self.calculate_exponential_decay(
                importance=importance,
                days_elapsed=days_elapsed,
                alpha=decay_params.get("alpha", 0.6),
                lambda1=decay_params.get("lambda1", 0.25),
                lambda2=decay_params.get("lambda2", 0.04),
            )

        level = self.get_level_from_importance(importance)
        return self.calculate_exponential_decay(
            importance=importance,
            days_elapsed=days_elapsed,
            alpha=level.params["alpha"],
            lambda1=level.params["lambda1"],
            lambda2=level.params["lambda2"],
        )

    def calculate_reactivation_score(
        self, base_score: float, reactivation_count: int, emotion_intensity: float = 0.0
    ) -> float:
        if reactivation_count <= 0:
            return base_score

        enhanced = base_score * (1.0 + 0.2 * reactivation_count) + 0.1
        emotion_bonus = 0.05 * abs(emotion_intensity)
        enhanced += emotion_bonus

        return min(enhanced, 1.0)

    def calculate_network_effect(
        self, base_score: float, active_memory_count: int, association_threshold: float = 0.6
    ) -> float:
        """
        计算网络效应增强

        网络增强 = 0.1 × √(关联的活跃记忆数量)
        最终时间分 = 基础时间分 + 网络增强（上限0.3）

        Args:
            base_score: 基础时间分数
            active_memory_count: 关联的活跃记忆数量
            association_threshold: 关联阈值

        Returns:
            增强后的时间分数
        """
        if active_memory_count <= 0:
            return base_score

        network_boost = 0.1 * math.sqrt(active_memory_count)
        network_boost = min(network_boost, 0.3)

        enhanced_score = base_score + network_boost

        return min(enhanced_score, 1.0)

    def calculate_relevance_score(
        self,
        memory: Dict,
        query_embedding: Optional[List[float]] = None,
        context_score: float = 0.0,
        keyword_match_count: int = 0,
    ) -> float:
        """
        计算相关性维度分数

        语义相似度（60%）+ 上下文关联（30%）+ 关键词匹配（10%）

        Args:
            memory: 记忆数据
            query_embedding: 查询向量嵌入
            context_score: 上下文关联分数
            keyword_match_count: 关键词匹配数量

        Returns:
            相关性分数
        """
        semantic_score = 0.6

        if query_embedding and memory.get("vector_id"):
            try:
                memory_embedding = memory.get("embedding")
                if memory_embedding:
                    similarity = np.dot(query_embedding, memory_embedding) / (
                        np.linalg.norm(query_embedding) * np.linalg.norm(memory_embedding)
                    )
                    semantic_score = max(0.0, min(1.0, similarity)) * 0.6
            except Exception as e:
                logger.warning(f"计算语义相似度失败: {e}")

        context_weight = 0.3
        context_score = max(0.0, min(1.0, context_score)) * context_weight

        keyword_weight = 0.1
        keyword_score = min(1.0, keyword_match_count / 5.0) * keyword_weight

        relevance_score = semantic_score + context_score + keyword_score

        return min(relevance_score, 1.0)

    def calculate_time_score(
        self, memory: Dict, apply_reactivation: bool = True, apply_network: bool = False
    ) -> float:
        """计算时间分数（基于当前时间实时计算）"""
        importance = memory.get("importance_score", memory.get("importance", 3) / 5.0)
        created_at = memory.get("created_at", datetime.now().isoformat())
        permanent = memory.get("permanent", False)

        if permanent:
            return 1.0

        decay_type = memory.get("decay_type", "exponential")
        decay_params = memory.get("decay_params")

        # 实时计算衰减分数
        time_score = self.calculate_decay(
            importance=importance,
            created_at=created_at,
            decay_type=decay_type,
            decay_params=decay_params,
        )

        if apply_reactivation:
            reactivation_count = memory.get("reactivation_count", 0)
            emotion_score = memory.get("emotion_score", 0.0)
            time_score = self.calculate_reactivation_score(
                base_score=time_score,
                reactivation_count=reactivation_count,
                emotion_intensity=emotion_score,
            )

        return max(time_score, 0.0)

    def calculate_time_score_realtime(
        self,
        importance: float,
        created_at: str,
        decay_type: str = "exponential",
        decay_params: Optional[Dict] = None,
        permanent: bool = False,
        reactivation_count: int = 0,
        emotion_score: float = 0.0,
    ) -> float:
        """实时计算时间分数（纯函数，不依赖内存状态）

        Args:
            importance: 重要性分数 (0-1)
            created_at: 创建时间 (ISO格式)
            decay_type: 衰减类型
            decay_params: 衰减参数
            permanent: 是否永久记忆
            reactivation_count: 再激活次数
            emotion_score: 情感分数

        Returns:
            实时计算的时间分数 (0-1)
        """
        if permanent or importance >= 0.95:
            return 1.0

        # 实时计算衰减
        time_score = self.calculate_decay(
            importance=importance,
            created_at=created_at,
            decay_type=decay_type,
            decay_params=decay_params,
        )

        # 应用再激活加成
        if reactivation_count > 0:
            time_score = self.calculate_reactivation_score(
                base_score=time_score,
                reactivation_count=reactivation_count,
                emotion_intensity=emotion_score,
            )

        return max(time_score, 0.0)

    def calculate_importance_score(self, memory: Dict) -> float:
        return memory.get("importance_score", memory.get("importance", 3) / 5.0)

    def calculate_final_score(
        self,
        memory: Dict,
        query_embedding=None,
        weights: Tuple[float, float, float] = (0.35, 0.25, 0.4),
        apply_reactivation: bool = True,
        apply_network: bool = False,
    ) -> float:
        importance_w, time_w, relevance_w = weights

        importance_score = self.calculate_importance_score(memory)

        time_score = self.calculate_time_score(
            memory=memory, apply_reactivation=apply_reactivation, apply_network=apply_network
        )

        relevance_score = memory.get("score", 0.5)

        base_score = (
            importance_score * importance_w + time_score * time_w + relevance_score * relevance_w
        )

        permanent = memory.get("permanent", False)
        if permanent:
            return min(base_score + 0.15, 1.0)

        return min(base_score, 1.0)


def importance_to_score(importance: int) -> float:
    if importance >= 5:
        return 0.95
    elif importance >= 4:
        return 0.77
    elif importance >= 3:
        return 0.60
    elif importance >= 2:
        return 0.40
    else:
        return 0.15


def score_to_importance(score: float) -> int:
    if score >= 0.9:
        return 5
    elif score >= 0.7:
        return 4
    elif score >= 0.5:
        return 3
    elif score >= 0.3:
        return 2
    else:
        return 1
