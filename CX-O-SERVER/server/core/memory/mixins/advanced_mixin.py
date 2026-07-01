"""MemoryManager mixin: Advanced search (3D search, recall) and decay/context management.

Extracted from manager.py as part of H5 mixin split.
"""
import asyncio
import json
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from server.config import Settings
from server.core.exceptions import DatabaseError, MemoryOperationError, VectorStoreError

from ._common import json_dumps, json_loads, logger

if TYPE_CHECKING:
    from server.core.memory.graph_store import GraphStoreBase


class _AdvancedSearchMixin:
    """Advanced search mixin: 3D search, recall, decay sync, decay statistics, memory context."""
    def search_memories_3d(
        self,
        query: str = None,
        memory_type: str = None,
        tags: List[str] = None,
        limit: int = 10,
        weights: Tuple[float, float, float] = (0.35, 0.25, 0.4),
        workspace_id: str = "default",
    ) -> List[Dict]:
        from server.core.memory.decay import DecayCalculator

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            conditions = ["workspace_id = ?", "is_deleted = FALSE"]
            params = [workspace_id]

            if query:
                conditions.append("content LIKE ?")
                params.append(f"%{query}%")

            if memory_type:
                conditions.append("type = ?")
                params.append(memory_type)

            if tags:
                for tag in tags:
                    conditions.append("tags LIKE ?")
                    params.append(f'%"{tag}"%')

            where_clause = " AND ".join(conditions)
            params.append(limit * 2)

            cursor.execute(
                f"SELECT * FROM memories WHERE {where_clause} ORDER BY importance DESC, created_at DESC LIMIT ?",
                params,
            )

            rows = cursor.fetchall()
        except Exception as e:
            logger.error(f"3D搜索失败: {e}", exc_info=True)
            rows = []

        decay_calculator = DecayCalculator()
        scored_memories = []

        for row in rows:
            memory = self._row_to_memory(row)

            importance_score = decay_calculator.calculate_importance_score(memory)
            time_score = decay_calculator.calculate_time_score(memory, apply_reactivation=True)
            relevance_score = memory.get("score", 0.5)

            final_score = (
                importance_score * weights[0]
                + time_score * weights[1]
                + relevance_score * weights[2]
            )

            if memory.get("permanent"):
                final_score = min(final_score + 0.15, 1.0)

            final_score = min(final_score, 1.0)

            memory["final_score"] = final_score
            memory["component_scores"] = {
                "importance": importance_score,
                "time": time_score,
                "relevance": relevance_score,
            }
            memory["applied_weights"] = {
                "importance": weights[0],
                "time": weights[1],
                "relevance": weights[2],
            }

            scored_memories.append(memory)

        scored_memories.sort(key=lambda m: m["final_score"], reverse=True)

        return scored_memories[:limit]

    def recall_memory(self, memory_id: int, emotion_intensity: float = 0.0) -> Optional[Dict]:
        from server.core.memory.decay import DecayCalculator

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND is_deleted = FALSE", (memory_id,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            memory = self._row_to_memory(row)

            reactivation_count = memory.get("reactivation_count", 0)
            decay_calculator = DecayCalculator()
            old_time_score = decay_calculator.calculate_time_score(memory, apply_reactivation=False)

            reactivation_bonus = 0.1 + 0.2 * reactivation_count
            emotion_bonus = 0.05 * abs(emotion_intensity)
            new_time_score = min(old_time_score + reactivation_bonus + emotion_bonus, 1.0)

            new_reactivation_count = reactivation_count + 1
            new_emotion_score = (memory.get("emotion_score", 0.0) + abs(emotion_intensity)) / 2

            cursor.execute(
                """
                UPDATE memories
                SET reactivation_count = ?, emotion_score = ?, updated_at = ?
                WHERE id = ?
            """,
                (new_reactivation_count, new_emotion_score, datetime.now().isoformat(), memory_id),
            )

            cursor.execute(
                """
                INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    "recall",
                    memory_id,
                    None,
                    "system",
                    json_dumps(
                        {
                            "reactivation_count": new_reactivation_count,
                            "emotion_intensity": emotion_intensity,
                            "old_time_score": old_time_score,
                            "new_time_score": new_time_score,
                            "memory_type": memory.get("type"),
                        }
                    ),
                ),
            )

            conn.commit()

            logger.info(f"记忆已召回: id={memory_id}, reactivation_count={new_reactivation_count}")

            updated_memory = self.get_memory(memory_id)
            if updated_memory:
                updated_memory["reactivation_details"] = {
                    "old_time_score": old_time_score,
                    "new_time_score": new_time_score,
                    "emotion_bonus": emotion_bonus,
                    "reactivation_count": new_reactivation_count,
                }

            return updated_memory
        except Exception as e:
            logger.error(f"召回记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return None

    def sync_decay_values(self, workspace_id: str = "default") -> Dict:
        """同步衰减值 - 已改为实时计算模式，此函数仅返回统计信息

        注意：时间分数现在实时计算，不再预存储到数据库
        """
        from server.core.memory.decay import DecayCalculator

        try:
            # 获取所有记忆用于统计
            memories = self.search_memories(limit=10000, workspace_id=workspace_id)

            decay_calculator = DecayCalculator()
            total = len(memories)
            permanent_count = sum(1 for m in memories if m.get("permanent"))

            # 实时计算统计信息
            time_scores = []
            for memory in memories:
                if not memory.get("permanent"):
                    time_score = decay_calculator.calculate_time_score_realtime(
                        importance=memory.get(
                            "importance_score", memory.get("importance", 3) / 5.0
                        ),
                        created_at=memory.get("created_at", datetime.now().isoformat()),
                        decay_type=memory.get("decay_type", "exponential"),
                        decay_params=memory.get("decay_params"),
                        permanent=False,
                        reactivation_count=memory.get("reactivation_count", 0),
                        emotion_score=memory.get("emotion_score", 0.0),
                    )
                    time_scores.append(time_score)

            avg_time_score = sum(time_scores) / len(time_scores) if time_scores else 0.0

            logger.info(
                f"衰减统计完成: 总计={total}, 永久={permanent_count}, 平均时间分={avg_time_score:.3f}"
            )

            return {
                "updated": 0,  # 不再更新数据库
                "failed": 0,
                "total": total,
                "permanent_count": permanent_count,
                "avg_time_score": avg_time_score,
                "mode": "realtime",  # 标记为实时计算模式
            }
        except Exception as e:
            logger.error(f"统计衰减值失败: {e}", exc_info=True)
            return {"updated": 0, "failed": 0, "total": 0, "error": str(e)}

    def get_decay_statistics(self, workspace_id: str = "default") -> Dict:
        from server.core.memory.decay import DecayCalculator

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM memories WHERE is_deleted = FALSE AND workspace_id = ?",
            (workspace_id,),
        )
        total = cursor.fetchone()[0]

        cursor.execute(
            """
            SELECT importance_score, COUNT(*)
            FROM memories
            WHERE is_deleted = FALSE AND workspace_id = ?
            GROUP BY importance_score
        """,
            (workspace_id,),
        )
        distribution = {row[0]: row[1] for row in cursor.fetchall()}

        decay_calculator = DecayCalculator()

        cursor.execute(
            "SELECT * FROM memories WHERE is_deleted = FALSE AND workspace_id = ?", (workspace_id,)
        )
        rows = cursor.fetchall()

        avg_time_score = 0.0
        avg_importance_score = 0.0
        reactivation_stats = {"total": 0, "avg_count": 0.0}

        for row in rows:
            memory = self._row_to_memory(row)

            if not memory.get("permanent"):
                time_score = decay_calculator.calculate_time_score(memory, apply_reactivation=True)
                avg_time_score += time_score

            avg_importance_score += memory.get("importance_score", 0.0)

            reactivation_count = memory.get("reactivation_count", 0)
            if reactivation_count > 0:
                reactivation_stats["total"] += 1
                reactivation_stats["avg_count"] += reactivation_count

        non_permanent_count = total - sum(
            1 for row in rows if self._row_to_memory(row).get("permanent")
        )

        if non_permanent_count > 0:
            avg_time_score /= non_permanent_count

        if total > 0:
            avg_importance_score /= total

        if reactivation_stats["total"] > 0:
            reactivation_stats["avg_count"] /= reactivation_stats["total"]

        return {
            "total_memories": total,
            "non_permanent_count": non_permanent_count,
            "permanent_count": total - non_permanent_count,
            "avg_time_score": round(avg_time_score, 4),
            "avg_importance_score": round(avg_importance_score, 4),
            "importance_distribution": distribution,
            "reactivation_stats": {
                "reactivated_count": reactivation_stats["total"],
                "avg_reactivation_count": round(reactivation_stats["avg_count"], 2),
            },
        }

    def get_memory_context(self, memory_id: int, depth: int = 2) -> Dict:
        """获取记忆的上下文信息

        Args:
            memory_id: 记忆ID
            depth: 上下文深度（查找相关记忆的层数）

        Returns:
            包含记忆上下文信息的字典
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 获取目标记忆
            cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND is_deleted = FALSE", (memory_id,)
            )
            row = cursor.fetchone()

            if not row:
                return {"status": "error", "message": "记忆不存在"}

            target_memory = self._row_to_memory(row)

            # 获取相关记忆（基于标签和时间接近性）
            context_memories = []
            target_tags = set(target_memory.get("tags", []))
            target_time = target_memory.get("created_at", "")

            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE id != ? AND is_deleted = FALSE 
                ORDER BY ABS(julianday(created_at) - julianday(?)) ASC
                LIMIT ?
            """,
                (memory_id, target_time, depth * 5),
            )

            for related_row in cursor.fetchall():
                related = self._row_to_memory(related_row)
                related_tags = set(related.get("tags", []))

                # 计算相似度
                tag_overlap = len(target_tags & related_tags)
                if tag_overlap > 0 or len(context_memories) < depth:
                    context_memories.append(
                        {
                            "memory": related,
                            "relevance_score": tag_overlap,
                            "relation_type": "temporal" if tag_overlap == 0 else "semantic",
                        }
                    )

            # 按相关度排序
            context_memories.sort(key=lambda x: x["relevance_score"], reverse=True)
            context_memories = context_memories[:depth]

            return {
                "status": "success",
                "target_memory": target_memory,
                "context_depth": depth,
                "related_memories": context_memories,
                "total_related": len(context_memories),
            }

        except Exception as e:
            logger.error(f"获取记忆上下文失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

