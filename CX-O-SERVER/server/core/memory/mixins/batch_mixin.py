"""MemoryManager mixin: Batch operations (batch write/update/delete/tags/archive).

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


class _BatchOperationsMixin:
    """Batch operations mixin: batch write/update/delete memories, batch update tags, batch archive."""
    def batch_write_memories(self, memories: List[Dict], raise_on_error: bool = False) -> Dict:
        results = {"success": 0, "failed": 0, "errors": [], "memory_ids": []}

        for mem_data in memories:
            try:
                memory_id = self.write_memory(
                    content=mem_data.get("content", ""),
                    memory_type=mem_data.get("type", "long_term"),
                    importance=mem_data.get("importance", 3),
                    tags=mem_data.get("tags", []),
                    metadata=mem_data.get("metadata", {}),
                    permanent=mem_data.get("permanent", False),
                    emotion_score=mem_data.get("emotion_score", 0.0),
                    workspace_id=mem_data.get("workspace_id", "default"),
                )
                results["success"] += 1
                results["memory_ids"].append(memory_id)
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
                if raise_on_error:
                    raise

        logger.info(f"批量写入完成: 成功={results['success']}, 失败={results['failed']}")
        return results

    def batch_update_memories(
        self, updates: List[Dict], raise_on_error: bool = False, agent_id: str = "default"
    ) -> Dict:
        """批量更新记忆

        Args:
            updates: 更新列表，每个包含 memory_id 和要更新的字段
            raise_on_error: 遇到错误是否抛出异常
            agent_id: Agent ID，用于指定记忆表
        """
        results = {"success": 0, "failed": 0, "errors": [], "updated_ids": []}

        for update_data in updates:
            try:
                memory_id = update_data.get("memory_id")
                if not memory_id:
                    raise ValueError("memory_id is required")

                success = self.update_memory(
                    memory_id=memory_id,
                    new_content=update_data.get("content"),
                    new_tags=update_data.get("tags"),
                    new_importance=update_data.get("importance"),
                    new_metadata=update_data.get("metadata"),
                    agent_id=agent_id,
                )

                if success:
                    results["success"] += 1
                    results["updated_ids"].append(memory_id)
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Memory {memory_id} not found")
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
                if raise_on_error:
                    raise

        logger.info(f"批量更新完成: 成功={results['success']}, 失败={results['failed']}")
        return results

    def batch_delete_memories(
        self,
        memory_ids: List[int],
        soft_delete: bool = True,
        raise_on_error: bool = False,
        agent_id: str = "default",
    ) -> Dict:
        """批量删除记忆

        Args:
            memory_ids: 记忆ID列表
            soft_delete: 是否软删除
            raise_on_error: 遇到错误是否抛出异常
            agent_id: Agent ID，用于指定记忆表
        """
        results = {"success": 0, "failed": 0, "errors": [], "deleted_ids": []}

        for memory_id in memory_ids:
            try:
                success = self.delete_memory(memory_id, soft_delete=soft_delete, agent_id=agent_id)

                if success:
                    results["success"] += 1
                    results["deleted_ids"].append(memory_id)
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Memory {memory_id} not found")
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))
                if raise_on_error:
                    raise

        logger.info(f"批量删除完成: 成功={results['success']}, 失败={results['failed']}")
        return results

    def batch_update_tags(
        self,
        memory_ids: List[int],
        tags: List[str],
        operation: str = "add",
        agent_id: str = "default",
    ) -> Dict:
        """批量更新记忆标签

        Args:
            memory_ids: 记忆ID列表
            tags: 标签列表
            operation: 操作类型 (add/remove/set)
            agent_id: Agent ID，用于指定记忆表

        Returns:
            更新结果
        """
        table_name = self._get_table_name(agent_id)
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            updated_count = 0
            failed_count = 0

            for memory_id in memory_ids:
                try:
                    cursor.execute(
                        f"SELECT tags FROM {table_name} WHERE id = ? AND is_deleted = FALSE",
                        (memory_id,),
                    )
                    row = cursor.fetchone()

                    if not row:
                        failed_count += 1
                        continue

                    try:
                        current_tags = set(json.loads(row[0]) if row[0] else [])
                    except Exception:
                        current_tags = set()

                    if operation == "add":
                        current_tags.update(tags)
                    elif operation == "remove":
                        current_tags.difference_update(tags)
                    elif operation == "set":
                        current_tags = set(tags)

                    new_tags = list(current_tags)

                    cursor.execute(
                        f"""
                        UPDATE {table_name} 
                        SET tags = ?, updated_at = ?
                        WHERE id = ?
                    """,
                        (
                            json.dumps(new_tags, ensure_ascii=False),
                            datetime.now().isoformat(),
                            memory_id,
                        ),
                    )

                    updated_count += 1
                except Exception as e:
                    logger.warning(f"更新记忆 {memory_id} 标签失败: {e}")
                    failed_count += 1

            conn.commit()

            logger.info(f"批量更新标签: 成功 {updated_count} 条, 失败 {failed_count} 条")

            return {
                "status": "success",
                "updated_count": updated_count,
                "failed_count": failed_count,
                "operation": operation,
                "tags": tags,
            }

        except Exception as e:
            logger.error(f"批量更新标签失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return {"status": "error", "message": str(e)}

    def batch_archive_memories(self, memory_ids: List[int], agent_id: str = "default") -> Dict:
        """批量归档记忆

        Args:
            memory_ids: 记忆ID列表
            agent_id: Agent ID，用于指定记忆表

        Returns:
            归档结果
        """
        table_name = self._get_table_name(agent_id)
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            archived_count = 0
            failed_count = 0
            now = datetime.now().isoformat()

            for memory_id in memory_ids:
                try:
                    # 将记忆标记为归档状态（通过设置 archived_at 字段）
                    cursor.execute(
                        f"""
                        UPDATE {table_name} 
                        SET archived_at = ?, updated_at = ?
                        WHERE id = ? AND is_deleted = FALSE
                    """,
                        (now, now, memory_id),
                    )

                    if cursor.rowcount > 0:
                        archived_count += 1
                    else:
                        failed_count += 1
                except Exception as e:
                    logger.warning(f"归档记忆 {memory_id} 失败: {e}")
                    failed_count += 1

            conn.commit()

            logger.info(f"批量归档: 成功 {archived_count} 条, 失败 {failed_count} 条")

            return {
                "status": "success",
                "archived_count": archived_count,
                "failed_count": failed_count,
            }

        except Exception as e:
            logger.error(f"批量归档失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return {"status": "error", "message": str(e)}

