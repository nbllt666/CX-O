"""MemoryManager mixin: Permanent memory operations (write/get/list/update/delete).

Extracted from manager.py as part of H5 mixin split.
"""
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING


from ._common import json_dumps, json_loads, logger

if TYPE_CHECKING:
    pass


class _PermanentMemoryMixin:
    """Permanent memory mixin: write/get/list/update/delete permanent memories."""
    def write_permanent_memory(
        self,
        content: str,
        tags: List[str] = None,
        metadata: Dict = None,
        emotion_score: float = 0.0,
        source: str = "user",
        is_from_main: bool = True,
    ) -> int:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO permanent_memories (
                    content, importance_score, emotion_score,
                    tags, metadata, created_at, source, verified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    content,
                    1.0,
                    emotion_score,
                    json_dumps(tags or [], ensure_ascii=False),
                    json_dumps(metadata or {}, ensure_ascii=False),
                    datetime.now().isoformat(),
                    source,
                    is_from_main,
                ),
            )

            memory_id = cursor.lastrowid

            cursor.execute(
                """
                INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    "create_permanent",
                    memory_id,
                    None,
                    "main_model" if is_from_main else "secondary_model",
                    json_dumps({"source": source}),
                ),
            )

            conn.commit()
            logger.info(f"永久记忆已写入: id={memory_id}, source={source}")
            return memory_id
        except Exception as e:
            logger.error(f"写入永久记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise

    def get_permanent_memory(self, memory_id: int) -> Optional[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM permanent_memories WHERE id = ?", (memory_id,))
            row = cursor.fetchone()

            if row:
                return self._row_to_permanent_memory(row)
            return None
        except Exception as e:
            logger.error(f"获取永久记忆失败: {e}", exc_info=True)
            return None

    def get_permanent_memories(
        self, limit: int = 20, offset: int = 0, tags: List[str] = None
    ) -> List[Dict]:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            query = "SELECT * FROM permanent_memories WHERE 1=1"
            params = []

            if tags:
                for tag in tags:
                    query += " AND tags LIKE ?"
                    params.append(f'%"{tag}"%')

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_permanent_memory(row) for row in rows]
        except Exception as e:
            logger.error(f"获取永久记忆列表失败: {e}", exc_info=True)
            return []

    def update_permanent_memory(
        self, memory_id: int, content: str = None, tags: List[str] = None, metadata: Dict = None
    ) -> bool:
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            updates = []
            params = []

            if content is not None:
                updates.append("content = ?")
                params.append(content)

            if tags is not None:
                updates.append("tags = ?")
                params.append(json_dumps(tags, ensure_ascii=False))

            if metadata is not None:
                updates.append("metadata = ?")
                params.append(json_dumps(metadata, ensure_ascii=False))

            if not updates:
                return False

            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(memory_id)

            query = f"UPDATE permanent_memories SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        "update_permanent",
                        memory_id,
                        None,
                        "system",
                        json_dumps({"updates": updates}),
                    ),
                )

            conn.commit()
            return success
        except Exception as e:
            logger.error(f"更新永久记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def delete_permanent_memory(self, memory_id: int, is_from_main: bool = True) -> bool:
        if not is_from_main:
            logger.warning(f"副模型无权删除永久记忆: id={memory_id}")
            return False

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM permanent_memories WHERE id = ?", (memory_id,))

            success = cursor.rowcount > 0

            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    ("delete_permanent", memory_id, None, "main_model", json_dumps({})),
                )

            conn.commit()
            return success
        except Exception as e:
            logger.error(f"删除永久记忆失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            return False

    def _row_to_permanent_memory(self, row) -> Dict:
        try:
            metadata = json_loads(row["metadata"] or "{}")
            tags = json_loads(row["tags"] or "[]")
        except Exception:
            metadata = {}
            tags = []

        return {
            "id": row["id"],
            "content": row["content"],
            "importance_score": row["importance_score"],
            "emotion_score": row["emotion_score"],
            "tags": tags,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "metadata": metadata,
            "source": row["source"],
            "verified": bool(row["verified"]) if "verified" in row.keys() else True,
        }
