"""MemoryManager mixin: Core CRUD operations and async wrappers.

Extracted from manager.py as part of H5 mixin split.
"""
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING


from ._common import json_dumps, json_loads, logger

if TYPE_CHECKING:
    pass


class _MemoryCRUDMixin:
    """Core CRUD mixin: write/get/search/update/delete/restore + async wrappers."""

    def write_memory(
        self,
        content: str,
        memory_type: str = "long_term",
        importance: int = 3,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        permanent: bool = False,
        emotion_score: float = 0.0,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> int:
        """写入记忆

        Args:
            content: 记忆内容
            memory_type: 记忆类型（long_term, short_term, permanent）
            importance: 重要性等级（1-5）
            tags: 标签列表
            metadata: 元数据
            permanent: 是否为永久记忆
            emotion_score: 情感分数
            workspace_id: 工作区ID
            agent_id: Agent ID，用于隔离不同Agent的记忆

        Returns:
            记忆ID

        Raises:
            DatabaseError: 数据库操作失败
        """
        # 确保Agent的记忆表存在
        self._ensure_agent_table(agent_id)
        table_name = self._get_table_name(agent_id)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"""
                INSERT INTO {table_name} (
                    type, content, importance, importance_score,
                    decay_type, decay_params, reactivation_count,
                    emotion_score, permanent, psychological_age,
                    tags, metadata, created_at, workspace_id, agent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    memory_type,
                    content,
                    importance,
                    0.6 if not permanent else 1.0,
                    "zero" if permanent else "exponential",
                    json_dumps({}),
                    0,
                    emotion_score,
                    permanent,
                    1.0,
                    json_dumps(tags or [], ensure_ascii=False),
                    json_dumps(metadata or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                    workspace_id,
                    agent_id,
                ),
            )

            memory_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO audit_logs (operation, memory_id, operator, details)
                VALUES (?, ?, ?, ?)
            """,
                (
                    "create",
                    memory_id,
                    "system",
                    json_dumps({"type": memory_type, "agent_id": agent_id}),
                ),
            )

            conn.commit()
            logger.info(f"记忆已写入: id={memory_id}, type={memory_type}, agent={agent_id}")

            try:
                vector_metadata = {
                    "type": memory_type,
                    "importance": importance,
                    "tags": tags or [],
                    "workspace_id": workspace_id,
                    "agent_id": agent_id,
                    "permanent": permanent,
                    "emotion_score": emotion_score,
                }
                self._sync_vector_for_memory(memory_id, content, vector_metadata)
            except Exception as vec_e:
                logger.warning(f"向量同步失败，不影响主操作: memory_id={memory_id}, error={vec_e}")

            if self._graph_enabled:
                try:
                    self._sync_to_graph(memory_id, content, tags=tags, metadata=metadata)
                except Exception as graph_e:
                    logger.warning(f"图同步失败，不影响主操作: memory_id={memory_id}, error={graph_e}")

            return memory_id
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"写入记忆失败: {e}", exc_info=True)
            raise

    def get_memory(
        self,
        memory_id: int,
        include_deleted: bool = False,
        agent_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """获取记忆

        Args:
            memory_id: 记忆ID
            include_deleted: 是否包含已删除的记忆
            agent_id: Agent唯一标识，指定时从Agent专属记忆表读取；
                None 时从默认 memories 表读取（保持向后兼容）

        Returns:
            记忆字典，如果不存在则返回None
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # agent_id 为 None 时保持原行为读 memories 表；
            # 否则按 _get_table_name 解析 Agent 专属表名（与 _ensure_agent_table 创建的表一致）
            table_name = self._get_table_name(agent_id) if agent_id else "memories"
            query = f"SELECT * FROM {table_name} WHERE id = ?"
            if not include_deleted:
                query += " AND is_deleted = FALSE"

            cursor.execute(query, (memory_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_memory(row)
            return None
        except Exception as e:
            logger.error(f"获取记忆失败: {e}", exc_info=True)
            return None

    def search_memories(
        self,
        query: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
        include_deleted: bool = False,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> List[Dict]:
        """搜索记忆

        Args:
            query: 搜索关键词
            memory_type: 记忆类型
            tags: 标签列表
            time_range: 时间范围（today, last_week, last_month）
            limit: 返回数量限制
            offset: 偏移量，用于分页
            include_deleted: 是否包含已删除的记忆
            workspace_id: 工作区ID
            agent_id: Agent ID，指定搜索哪个Agent的记忆表

        Returns:
            记忆列表
        """
        table_name = self._get_table_name(agent_id)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            conditions = ["workspace_id = ?"]
            params = [workspace_id]

            if query:
                escaped_query = query.replace("%", "\\%").replace("_", "\\_")
                conditions.append("content LIKE ? ESCAPE '\\'")
                params.append(f"%{escaped_query[:500]}%")

            if memory_type:
                conditions.append("type = ?")
                params.append(memory_type)

            if tags:
                for tag in tags:
                    escaped_tag = tag.replace("%", "\\%").replace("_", "\\_")
                    conditions.append("tags LIKE ? ESCAPE '\\'")
                    params.append(f'%"{escaped_tag[:100]}"%')

            if time_range:
                from datetime import timedelta

                now = datetime.now()
                if time_range == "today":
                    start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
                elif time_range == "last_week":
                    start_time = now - timedelta(days=7)
                elif time_range == "last_month":
                    start_time = now - timedelta(days=30)
                else:
                    start_time = now - timedelta(days=1)
                conditions.append("created_at >= ?")
                params.append(start_time.isoformat())

            if not include_deleted:
                conditions.append("is_deleted = FALSE")

            where_clause = " AND ".join(conditions) if conditions else "1=1"
            params.append(limit)
            params.append(offset)

            cursor.execute(
                f"SELECT * FROM {table_name} WHERE {where_clause} ORDER BY importance DESC, created_at DESC LIMIT ? OFFSET ?",
                params,
            )

            rows = cursor.fetchall()
            return [self._row_to_memory(row) for row in rows]
        except Exception as e:
            logger.error(f"搜索记忆失败: {e}", exc_info=True)
            return []

    def update_memory(
        self,
        memory_id: int,
        new_content: str = None,
        new_tags: List[str] = None,
        new_importance: int = None,
        new_metadata: Dict = None,
        agent_id: str = "default",
    ) -> bool:
        """更新记忆

        Args:
            memory_id: 记忆ID
            new_content: 新内容
            new_tags: 新标签
            new_importance: 新重要性
            new_metadata: 新元数据
            agent_id: Agent ID，用于指定记忆表
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            updates = []
            params = []

            if new_content is not None:
                updates.append("content = ?")
                params.append(new_content)

            if new_tags is not None:
                updates.append("tags = ?")
                params.append(json_dumps(new_tags, ensure_ascii=False))

            if new_importance is not None:
                updates.append("importance = ?")
                params.append(new_importance)

            if new_metadata is not None:
                updates.append("metadata = ?")
                params.append(json_dumps(new_metadata, ensure_ascii=False))

            if not updates:
                return False

            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(memory_id)

            query = (
                f"UPDATE {table_name} SET {', '.join(updates)} WHERE id = ? AND is_deleted = FALSE"
            )
            cursor.execute(query, params)

            success = cursor.rowcount > 0
            conn.commit()

            if success and new_content is not None:
                try:
                    vector_metadata = {
                        "tags": new_tags or [],
                        "importance": new_importance,
                        "agent_id": agent_id,
                    }
                    if new_metadata:
                        vector_metadata.update(new_metadata)
                    self._update_vector_for_memory(memory_id, new_content, vector_metadata)
                except Exception as vec_e:
                    logger.warning(
                        f"向量更新失败，不影响主操作: memory_id={memory_id}, error={vec_e}"
                    )

            return success
        except Exception as e:
            logger.error(f"更新记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def delete_memory(
        self, memory_id: int, soft_delete: bool = True, agent_id: str = "default"
    ) -> bool:
        """删除记忆

        Args:
            memory_id: 记忆ID
            soft_delete: 是否软删除
            agent_id: Agent ID，用于指定记忆表
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            if soft_delete:
                query = f"UPDATE {table_name} SET is_deleted = TRUE, updated_at = ? WHERE id = ? AND is_deleted = FALSE"
                params = (datetime.now().isoformat(), memory_id)
            else:
                query = f"DELETE FROM {table_name} WHERE id = ?"
                params = (memory_id,)

            cursor.execute(query, params)

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, operator, details)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        "delete" if not soft_delete else "soft_delete",
                        memory_id,
                        "system",
                        json_dumps({"soft_delete": soft_delete, "agent_id": agent_id}),
                    ),
                )

            conn.commit()

            if success:
                try:
                    self._delete_vector_for_memory(memory_id)
                except Exception as vec_e:
                    logger.warning(
                        f"向量删除失败，不影响主操作: memory_id={memory_id}, error={vec_e}"
                    )

            if success and self._graph_enabled:
                try:
                    self._update_graph_on_delete(memory_id)
                except Exception as graph_e:
                    logger.warning(
                        f"图数据库更新失败，不影响主操作: memory_id={memory_id}, error={graph_e}"
                    )

            return success
        except Exception as e:
            logger.error(f"删除记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def restore_memory(self, memory_id: int, agent_id: str = "default") -> bool:
        """恢复软删除的记忆

        Args:
            memory_id: 记忆ID
            agent_id: Agent ID，用于指定记忆表
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"""
                UPDATE {table_name} 
                SET is_deleted = FALSE, updated_at = ?
                WHERE id = ? AND is_deleted = TRUE
            """,
                (datetime.now().isoformat(), memory_id),
            )

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, operator, details)
                    VALUES (?, ?, ?, ?)
                """,
                    ("restore", memory_id, "system", json_dumps({"agent_id": agent_id})),
                )

            conn.commit()
            return success
        except Exception as e:
            logger.error(f"恢复记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def get_statistics(self, workspace_id: str = "default") -> Dict:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE is_deleted = FALSE AND workspace_id = ?",
                (workspace_id,),
            )
            total = cursor.fetchone()[0]

            cursor.execute(
                "SELECT type, COUNT(*) FROM memories WHERE is_deleted = FALSE AND workspace_id = ? GROUP BY type",
                (workspace_id,),
            )
            by_type = {row[0]: row[1] for row in cursor.fetchall()}

            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE is_deleted = TRUE AND workspace_id = ?",
                (workspace_id,),
            )
            soft_deleted = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE permanent = TRUE AND is_deleted = FALSE AND workspace_id = ?",
                (workspace_id,),
            )
            permanent = cursor.fetchone()[0]

            return {
                "total": total,
                "by_type": by_type,
                "soft_deleted": soft_deleted,
                "permanent": permanent,
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}", exc_info=True)
            return {"total": 0, "by_type": {}, "soft_deleted": 0, "permanent": 0}

    def _row_to_memory(self, row) -> Dict:
        try:
            metadata = json_loads(row["metadata"] or "{}")
            tags = json_loads(row["tags"] or "[]")
            decay_params = json_loads(row["decay_params"] or "{}")
        except Exception:
            metadata = {}
            tags = []
            decay_params = {}

        return {
            "id": row["id"],
            "type": row["type"],
            "content": row["content"],
            "vector_id": row["vector_id"],
            "metadata": metadata,
            "importance": row["importance"],
            "importance_score": row["importance_score"],
            "decay_type": row["decay_type"],
            "decay_params": decay_params,
            "reactivation_count": row["reactivation_count"],
            "emotion_score": row["emotion_score"],
            "permanent": bool(row["permanent"]),
            "psychological_age": row["psychological_age"],
            "tags": tags,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
            "is_deleted": bool(row["is_deleted"]),
            "source": row["source"],
            "workspace_id": row["workspace_id"],
        }

    async def write_memory_async(
        self,
        content: str,
        memory_type: str = "long_term",
        importance: int = 3,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        permanent: bool = False,
        emotion_score: float = 0.0,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> int:
        """异步写入记忆（通过 to_thread 包装同步 sqlite 调用）"""
        return await asyncio.to_thread(
            self.write_memory,
            content=content,
            memory_type=memory_type,
            importance=importance,
            tags=tags,
            metadata=metadata,
            permanent=permanent,
            emotion_score=emotion_score,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

    async def get_memory_async(
        self, memory_id: int, include_deleted: bool = False
    ) -> Optional[Dict]:
        """异步获取记忆"""
        return await asyncio.to_thread(self.get_memory, memory_id, include_deleted)

    async def search_memories_async(
        self,
        query: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        time_range: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
        include_deleted: bool = False,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> List[Dict]:
        """异步搜索记忆"""
        return await asyncio.to_thread(
            self.search_memories,
            query=query,
            memory_type=memory_type,
            tags=tags,
            time_range=time_range,
            limit=limit,
            offset=offset,
            include_deleted=include_deleted,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

    async def update_memory_async(
        self,
        memory_id: int,
        new_content: str = None,
        new_tags: List[str] = None,
        new_importance: int = None,
        new_metadata: Dict = None,
        agent_id: str = "default",
    ) -> bool:
        """异步更新记忆"""
        return await asyncio.to_thread(
            self.update_memory,
            memory_id=memory_id,
            new_content=new_content,
            new_tags=new_tags,
            new_importance=new_importance,
            new_metadata=new_metadata,
            agent_id=agent_id,
        )

    async def delete_memory_async(
        self, memory_id: int, soft_delete: bool = True, agent_id: str = "default"
    ) -> bool:
        """异步删除记忆"""
        return await asyncio.to_thread(
            self.delete_memory, memory_id, soft_delete, agent_id
        )

    async def get_statistics_async(self, workspace_id: str = "default") -> Dict:
        """异步获取记忆统计"""
        return await asyncio.to_thread(self.get_statistics, workspace_id)
