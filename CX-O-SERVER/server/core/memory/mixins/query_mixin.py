"""MemoryManager mixin: Query helpers (session cleanup, tag search, timeline, stats, type/emotion queries).

Extracted from manager.py as part of H5 mixin split.
"""
import json
from datetime import datetime
from typing import Dict, List, Tuple, TYPE_CHECKING

from server.config import Settings

from ._common import logger

if TYPE_CHECKING:
    pass


class _QueryHelpersMixin:
    """Query helpers mixin: cleanup old sessions, search by tag, timeline, statistics, session memories, type/emotion/relationship queries."""
    def cleanup_old_sessions(self, days: int = 30) -> Dict:
        """清理过期的会话记忆

        Args:
            days: 多少天前的会话被视为过期

        Returns:
            清理结果统计
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 查找过期的短期记忆
            cursor.execute(
                """
                SELECT id FROM memories 
                WHERE type = 'short_term' 
                AND is_deleted = FALSE
                AND julianday('now') - julianday(created_at) > ?
            """,
                (days,),
            )

            old_ids = [row[0] for row in cursor.fetchall()]

            if not old_ids:
                return {
                    "status": "success",
                    "cleaned_count": 0,
                    "message": "没有需要清理的过期会话",
                }

            # 软删除这些记忆
            placeholders = ",".join("?" * len(old_ids))
            cursor.execute(
                f"""
                UPDATE memories 
                SET is_deleted = TRUE, deleted_at = ?
                WHERE id IN ({placeholders})
            """,
                (datetime.now().isoformat(), *old_ids),
            )

            conn.commit()

            logger.info(f"清理了 {len(old_ids)} 个过期会话记忆")

            return {
                "status": "success",
                "cleaned_count": len(old_ids),
                "days_threshold": days,
                "message": f"成功清理 {len(old_ids)} 个过期会话记忆",
            }

        except Exception as e:
            logger.error(f"清理过期会话失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return {"status": "error", "message": str(e)}

    def search_by_tag(self, tag: str, workspace_id: str = "default", limit: int = 50) -> List[Dict]:
        """通过标签搜索记忆

        Args:
            tag: 要搜索的标签
            workspace_id: 工作区ID
            limit: 返回结果数量限制

        Returns:
            匹配的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 使用 JSON 搜索标签
            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE is_deleted = FALSE 
                AND workspace_id = ?
                AND tags LIKE ?
                ORDER BY importance_score DESC, created_at DESC
                LIMIT ?
            """,
                (workspace_id, f'%"{tag}"%', limit),
            )

            results = []
            for row in cursor.fetchall():
                memory = self._row_to_memory(row)
                tags = memory.get("tags", [])
                if tag in tags:
                    results.append(memory)

            return results

        except Exception as e:
            logger.error(f"标签搜索失败: {e}", exc_info=True)
            return []

    def get_memory_timeline(self, workspace_id: str = "default", days: int = 30) -> Dict:
        """获取记忆时间线

        Args:
            workspace_id: 工作区ID
            days: 时间范围（天）

        Returns:
            按时间分组的记忆统计
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT 
                    date(created_at) as date,
                    COUNT(*) as count,
                    type,
                    AVG(importance_score) as avg_importance
                FROM memories 
                WHERE is_deleted = FALSE 
                AND workspace_id = ?
                AND julianday('now') - julianday(created_at) <= ?
                GROUP BY date(created_at), type
                ORDER BY date DESC
            """,
                (workspace_id, days),
            )

            timeline = {}
            for row in cursor.fetchall():
                date_str = row[0]
                if date_str not in timeline:
                    timeline[date_str] = {"total": 0, "types": {}, "avg_importance": 0.0}

                timeline[date_str]["types"][row[2]] = row[1]
                timeline[date_str]["total"] += row[1]
                timeline[date_str]["avg_importance"] = round(row[3], 4) if row[3] else 0.0

            return {
                "status": "success",
                "days": days,
                "timeline": timeline,
                "total_days": len(timeline),
            }

        except Exception as e:
            logger.error(f"获取时间线失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def get_memory_statistics(self, workspace_id: str = "default") -> Dict:
        """获取记忆统计信息

        Args:
            workspace_id: 工作区ID

        Returns:
            详细的记忆统计数据
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 基础统计
            cursor.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN type = 'long_term' THEN 1 ELSE 0 END) as long_term,
                    SUM(CASE WHEN type = 'short_term' THEN 1 ELSE 0 END) as short_term,
                    SUM(CASE WHEN permanent = TRUE THEN 1 ELSE 0 END) as permanent,
                    AVG(importance_score) as avg_importance,
                    AVG(emotion_score) as avg_emotion
                FROM memories 
                WHERE is_deleted = FALSE AND workspace_id = ?
            """,
                (workspace_id,),
            )

            row = cursor.fetchone()

            # 标签统计
            cursor.execute(
                """
                SELECT tags FROM memories 
                WHERE is_deleted = FALSE AND workspace_id = ?
            """,
                (workspace_id,),
            )

            tag_counts = {}
            for tag_row in cursor.fetchall():
                try:
                    tags = json.loads(tag_row[0]) if tag_row[0] else []
                    for tag in tags:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
                except Exception:
                    logger.warning("解析记忆标签失败，跳过该行: %s", tag_row, exc_info=True)

            # 获取热门标签
            top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

            return {
                "status": "success",
                "workspace_id": workspace_id,
                "total_memories": row[0] or 0,
                "by_type": {
                    "long_term": row[1] or 0,
                    "short_term": row[2] or 0,
                    "permanent": row[3] or 0,
                },
                "avg_importance_score": round(row[4], 4) if row[4] else 0.0,
                "avg_emotion_score": round(row[5], 4) if row[5] else 0.0,
                "top_tags": top_tags,
                "total_unique_tags": len(tag_counts),
            }

        except Exception as e:
            logger.error(f"获取统计信息失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def get_session_memories(self, session_id: str, limit: int = 100) -> List[Dict]:
        """获取特定会话的记忆

        Args:
            session_id: 会话ID
            limit: 返回结果数量限制

        Returns:
            会话相关的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # 从 audit_logs 中查找会话相关的记忆
            cursor.execute(
                """
                SELECT m.* FROM memories m
                JOIN audit_logs al ON m.id = al.memory_id
                WHERE al.session_id = ?
                AND m.is_deleted = FALSE
                ORDER BY al.timestamp DESC
                LIMIT ?
            """,
                (session_id, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_memory(row))

            return results

        except Exception as e:
            logger.error(f"获取会话记忆失败: {e}", exc_info=True)
            return []

    def get_memories_by_type(
        self, memory_type: str, workspace_id: str = "default", limit: int = 100
    ) -> List[Dict]:
        """按类型获取记忆

        Args:
            memory_type: 记忆类型 (long_term/short_term/permanent)
            workspace_id: 工作区ID
            limit: 返回结果数量限制

        Returns:
            指定类型的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            if memory_type == "permanent":
                cursor.execute(
                    """
                    SELECT * FROM memories 
                    WHERE permanent = TRUE 
                    AND is_deleted = FALSE
                    AND workspace_id = ?
                    ORDER BY importance_score DESC
                    LIMIT ?
                """,
                    (workspace_id, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT * FROM memories 
                    WHERE type = ? 
                    AND is_deleted = FALSE
                    AND workspace_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (memory_type, workspace_id, limit),
                )

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_memory(row))

            return results

        except Exception as e:
            logger.error(f"按类型获取记忆失败: {e}", exc_info=True)
            return []

    def get_memory_relationships(self, memory_id: int) -> Dict:
        """获取记忆的关系网络

        Args:
            memory_id: 记忆ID

        Returns:
            记忆关系信息
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

            target = self._row_to_memory(row)
            target_tags = set(target.get("tags", []))

            # 查找相关记忆
            relationships = []

            # 基于标签的相关性
            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE id != ? AND is_deleted = FALSE
            """,
                (memory_id,),
            )

            for related_row in cursor.fetchall():
                related = self._row_to_memory(related_row)
                related_tags = set(related.get("tags", []))

                common_tags = target_tags & related_tags
                if common_tags:
                    relationships.append(
                        {
                            "memory_id": related["id"],
                            "relation_type": "tag_similarity",
                            "strength": len(common_tags),
                            "common_tags": list(common_tags),
                        }
                    )

            # 按关系强度排序
            relationships.sort(key=lambda x: x["strength"], reverse=True)

            return {
                "status": "success",
                "memory_id": memory_id,
                "relationships": relationships[:Settings().config.limits.memory.max_relationships],
                "total_relationships": len(relationships),
            }

        except Exception as e:
            logger.error(f"获取记忆关系失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def get_memories_by_emotion(
        self, emotion_range: Tuple[float, float], workspace_id: str = "default", limit: int = 50
    ) -> List[Dict]:
        """按情感分数范围获取记忆

        Args:
            emotion_range: 情感分数范围 (min, max)
            workspace_id: 工作区ID
            limit: 返回结果数量限制

        Returns:
            符合条件的记忆列表
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            min_emotion, max_emotion = emotion_range

            cursor.execute(
                """
                SELECT * FROM memories 
                WHERE emotion_score >= ? 
                AND emotion_score <= ?
                AND is_deleted = FALSE
                AND workspace_id = ?
                ORDER BY ABS(emotion_score - ?) ASC
                LIMIT ?
            """,
                (min_emotion, max_emotion, workspace_id, (min_emotion + max_emotion) / 2, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append(self._row_to_memory(row))

            return results

        except Exception as e:
            logger.error(f"按情感获取记忆失败: {e}", exc_info=True)
            return []

    def get_emotion_peak_since(self, since_iso: str, workspace_id: str = "default") -> Dict:
        """查询自指定时间以来的情绪峰值与事件数（排除梦境记忆）

        供梦境情绪触发闸门使用：聚合最近事件窗口内 emotion_score 绝对值的最大值，
        并排除 type='dream' 的梦境记忆，避免梦境内容自我强化情绪峰值。

        Args:
            since_iso: 起始时间（ISO 格式字符串，含该时刻及之后）
            workspace_id: 工作区ID

        Returns:
            {"peak": float, "count": int}；查询失败时降级返回 {"peak": 0.0, "count": 0}
        """
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COALESCE(MAX(ABS(emotion_score)), 0.0) AS peak, COUNT(*) AS cnt
                FROM memories
                WHERE is_deleted = FALSE
                AND workspace_id = ?
                AND created_at >= ?
                AND (type IS NULL OR type != 'dream')
                """,
                (workspace_id, since_iso),
            )

            row = cursor.fetchone()
            return {
                "peak": float(row["peak"] or 0.0),
                "count": int(row["cnt"] or 0),
            }

        except Exception as e:
            logger.error(f"查询情绪峰值失败: {e}", exc_info=True)
            return {"peak": 0.0, "count": 0}

