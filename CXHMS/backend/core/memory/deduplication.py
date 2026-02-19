"""
去重检测模块
检测相似记忆并记录重复关系
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class DuplicateGroup:
    """去重组"""

    group_id: str
    memory_ids: List[int] = field(default_factory=list)
    canonical_id: Optional[int] = None  # 代表记忆ID
    similarity_matrix: Dict[str, float] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    merged: bool = False
    merged_at: Optional[str] = None
    merged_into: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "memory_ids": self.memory_ids,
            "canonical_id": self.canonical_id,
            "similarity_matrix": self.similarity_matrix,
            "created_at": self.created_at,
            "merged": self.merged,
            "merged_at": self.merged_at,
            "merged_into": self.merged_into,
        }


@dataclass
class SimilarityRecord:
    """相似性记录"""

    memory_id_1: int
    memory_id_2: int
    similarity_score: float
    checked_at: str = field(default_factory=lambda: datetime.now().isoformat())
    is_duplicate: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id_1": self.memory_id_1,
            "memory_id_2": self.memory_id_2,
            "similarity_score": self.similarity_score,
            "checked_at": self.checked_at,
            "is_duplicate": self.is_duplicate,
        }


class DeduplicationEngine:
    """去重检测引擎"""

    def __init__(self, memory_manager, threshold: float = 0.85):
        self.memory_manager = memory_manager
        self.threshold = threshold
        self._similarity_cache: Dict[str, float] = {}
        self._duplicate_groups: Dict[str, DuplicateGroup] = {}

    def _generate_group_id(self, memory_ids: List[int]) -> str:
        """生成去重组ID"""
        sorted_ids = sorted(memory_ids)
        id_str = ",".join(map(str, sorted_ids))
        return hashlib.md5(id_str.encode()).hexdigest()[:16]

    async def check_similarity(self, memory_id_1: int, memory_id_2: int) -> float:
        """检查两个记忆的相似度

        使用文本内容的相似度计算（基于向量存储或文本相似度）
        """
        cache_key = f"{min(memory_id_1, memory_id_2)}:{max(memory_id_1, memory_id_2)}"

        if cache_key in self._similarity_cache:
            return self._similarity_cache[cache_key]

        try:
            # 获取记忆内容
            memory_1 = self.memory_manager.get_memory(memory_id_1)
            memory_2 = self.memory_manager.get_memory(memory_id_2)

            if not memory_1 or not memory_2:
                return 0.0

            content_1 = memory_1.get("content", "")
            content_2 = memory_2.get("content", "")

            # 计算文本相似度（使用简单的Jaccard相似度）
            similarity = self._calculate_text_similarity(content_1, content_2)

            # 缓存结果
            self._similarity_cache[cache_key] = similarity

            return similarity

        except Exception as e:
            logger.error(f"计算相似度失败: {e}", exc_info=True)
            return 0.0

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的Jaccard相似度

        Args:
            text1: 第一个文本
            text2: 第二个文本

        Returns:
            相似度分数 (0.0 - 1.0)
        """
        if not text1 or not text2:
            return 0.0

        # 转换为小写并分割成词集合
        set1 = set(text1.lower().split())
        set2 = set(text2.lower().split())

        if not set1 or not set2:
            return 0.0

        # 计算Jaccard相似度
        intersection = len(set1 & set2)
        union = len(set1 | set2)

        if union == 0:
            return 0.0

        return intersection / union

    async def find_similar_memories(
        self, memory_id: int, threshold: float = None, limit: int = 10
    ) -> List[SimilarityRecord]:
        """查找与指定记忆相似的其他记忆"""
        if threshold is None:
            threshold = self.threshold

        similar_memories = []

        try:
            # 获取所有记忆
            all_memories = self.memory_manager.search_memories(
                memory_type=None, limit=10000, include_deleted=False
            )

            for other_memory in all_memories:
                other_id = other_memory["id"]
                if other_id == memory_id:
                    continue

                similarity = await self.check_similarity(memory_id, other_id)

                if similarity >= threshold:
                    record = SimilarityRecord(
                        memory_id_1=memory_id,
                        memory_id_2=other_id,
                        similarity_score=similarity,
                        is_duplicate=similarity >= self.threshold,
                    )
                    similar_memories.append(record)

            # 按相似度排序
            similar_memories.sort(key=lambda x: x.similarity_score, reverse=True)

            return similar_memories[:limit]

        except Exception as e:
            logger.error(f"查找相似记忆失败: {e}")
            return []

    async def detect_duplicates_batch(
        self, memory_ids: List[int] = None, threshold: float = None
    ) -> List[DuplicateGroup]:
        """批量检测重复记忆"""
        if threshold is None:
            threshold = self.threshold

        if memory_ids is None:
            # 获取所有记忆
            all_memories = self.memory_manager.search_memories(
                memory_type=None, limit=10000, include_deleted=False
            )
            memory_ids = [m["id"] for m in all_memories]

        # 构建相似性图
        similarity_graph: Dict[int, Set[int]] = {mid: set() for mid in memory_ids}

        logger.info(f"开始批量去重检测，记忆数量: {len(memory_ids)}")

        # 计算所有记忆对的相似度
        for i, id_1 in enumerate(memory_ids):
            for id_2 in memory_ids[i + 1 :]:
                similarity = await self.check_similarity(id_1, id_2)

                if similarity >= threshold:
                    similarity_graph[id_1].add(id_2)
                    similarity_graph[id_2].add(id_1)

        # 使用并查集找到连通分量（重复组）
        groups = self._find_connected_components(similarity_graph)

        # 创建 DuplicateGroup 对象
        duplicate_groups = []
        for group_memories in groups:
            if len(group_memories) > 1:  # 只保留有重复的记忆组
                group_id = self._generate_group_id(list(group_memories))

                # 计算相似度矩阵
                similarity_matrix = {}
                for id_1 in group_memories:
                    for id_2 in group_memories:
                        if id_1 < id_2:
                            sim = await self.check_similarity(id_1, id_2)
                            similarity_matrix[f"{id_1}:{id_2}"] = sim

                # 选择代表性记忆（创建时间最早的）
                def get_created_time(memory_id):
                    memory = self.memory_manager.get_memory(memory_id)
                    if memory is None:
                        return ""
                    return memory.get("created_at", "")

                canonical_id = min(group_memories, key=get_created_time)

                group = DuplicateGroup(
                    group_id=group_id,
                    memory_ids=list(group_memories),
                    canonical_id=canonical_id,
                    similarity_matrix=similarity_matrix,
                )

                duplicate_groups.append(group)
                self._duplicate_groups[group_id] = group

        logger.info(f"检测到 {len(duplicate_groups)} 个重复组")

        return duplicate_groups

    def _find_connected_components(self, graph: Dict[int, Set[int]]) -> List[Set[int]]:
        """查找连通分量"""
        visited = set()
        components = []

        def dfs(node, component):
            visited.add(node)
            component.add(node)
            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor, component)

        for node in graph:
            if node not in visited:
                component = set()
                dfs(node, component)
                components.append(component)

        return components

    async def record_search_similarity(
        self, query_memory_id: int, result_memory_id: int, similarity_score: float
    ):
        """记录搜索时发现的相似性"""
        if similarity_score >= self.threshold:
            logger.info(
                f"搜索发现重复记忆",
                extra={
                    "query_memory_id": query_memory_id,
                    "result_memory_id": result_memory_id,
                    "similarity_score": similarity_score,
                },
            )

            # 注意：这里可以扩展为将相似性记录保存到数据库
            # 目前仅记录到日志中

    def get_duplicate_groups(self) -> List[DuplicateGroup]:
        """获取所有去重组"""
        return list(self._duplicate_groups.values())

    def get_duplicate_group_by_memory(self, memory_id: int) -> Optional[DuplicateGroup]:
        """根据记忆ID获取所属的去重组"""
        for group in self._duplicate_groups.values():
            if memory_id in group.memory_ids:
                return group
        return None

    def clear_cache(self):
        """清除相似度缓存"""
        self._similarity_cache.clear()
        logger.info("相似度缓存已清除")
