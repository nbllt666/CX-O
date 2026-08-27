"""MemoryManager mixin: DecisionCore 集成（rejected_content 表 + write_with_decision）。

CX-O 迁移版 B4.3：为 MemoryManager 新增 3 方法，支持 DecisionCore D6_REJECT
决策将被拒绝内容写入 rejected_content 表（保留 retention_days 天后清理）。

对应契约:
    - 数据契约: public/schema/rejected_content.schema.json
    - 异常契约: rejected_content.schema.json definitions.exceptions

@version 1.0.0
"""
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from ._common import json_dumps, json_loads, logger

from server.core.utils import new_uuid as _new_uuid


def _decision_field(decision: Any, field: str, default: Any = None) -> Any:
    """从 StorageDecision 对象或 dict 兼容读取字段（duck typing）。"""
    if isinstance(decision, dict):
        return decision.get(field, default)
    return getattr(decision, field, default)


def _rubric_snapshot_to_dict(rubric: Any) -> Dict[str, Any]:
    """rubric_snapshot 序列化为 dict（兼容 Pydantic 模型与 dict）。"""
    if rubric is None:
        return {}
    if isinstance(rubric, dict):
        return rubric
    if hasattr(rubric, "model_dump"):
        return rubric.model_dump()
    if hasattr(rubric, "dict"):
        return rubric.dict()
    return dict(rubric)


class _DecisionMixin:
    """DecisionCore 集成 mixin。

    提供 3 方法 + rejected_content 表初始化：
        - write_with_decision(content, decision, metadata)
        - get_rejected_content(session_id, limit)
        - cleanup_expired_rejected_content(retention_days)
        - _init_rejected_content_table()

    rejected_content 表 schema 严格对应 public/schema/rejected_content.schema.json。
    """

    def _init_rejected_content_table(self) -> None:
        """初始化 rejected_content 表（CREATE TABLE IF NOT EXISTS）。

        schema 对应 public/schema/rejected_content.schema.json。
        幂等：重复调用不报错。
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS rejected_content (
                    rejected_id VARCHAR(36) PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    original_content TEXT NOT NULL,
                    source_artifact_id VARCHAR(36),
                    source_type VARCHAR(30),
                    quality_score FLOAT NOT NULL,
                    reject_reason TEXT NOT NULL,
                    decision_point VARCHAR(20) DEFAULT 'D6_REJECT',
                    rubric_snapshot TEXT,
                    llm_reasoning TEXT,
                    llm_confidence FLOAT,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL,
                    is_purged BOOLEAN DEFAULT FALSE,
                    purged_at TIMESTAMP,
                    human_overridden BOOLEAN DEFAULT FALSE
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_rejected_session ON rejected_content(session_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_rejected_expires ON rejected_content(expires_at)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_rejected_purged ON rejected_content(is_purged)"
            )
            conn.commit()
            logger.debug("rejected_content 表已就绪")
        except Exception as e:
            logger.error(f"初始化 rejected_content 表失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise RuntimeError(f"rejected_content 表初始化失败（500）: {e}") from e
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）

    def write_with_decision(
        self,
        content: str,
        decision: Any,
        metadata: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
    ) -> Dict[str, Any]:
        """按 decision.location 决定写入主库或 rejected_content 表。

        - location=memories → write_memory（临时记忆）
        - location=permanent_memories → write_permanent_memory（永久记忆）
        - location=rejected → 写入 rejected_content 表（保留 retention_days 天）

        Args:
            content: 记忆/被拒绝内容
            decision: StorageDecision 对象或 dict（含 location/quality_score/reason/
                      rubric_snapshot/decision_point/llm_reasoning/llm_confidence 等字段）
            metadata: 附加元数据（写入主库时合并到记忆 metadata；写入 rejected 时合并到
                      rejected_content.metadata）
            source: 来源标记透传（'vision'/'user' 等）。memories 分支默认 'user'；
                    permanent_memories 分支缺省维持原硬编码 'radix_decision'。

        Returns:
            {"location": str, "memory_id": Optional[int], "rejected_id": Optional[str]}

        Raises:
            ValueError: decision.location 无效（422）
            RuntimeError: 写入失败（500）
        """
        location = _decision_field(decision, "location")
        if location not in ("memories", "permanent_memories", "rejected"):
            raise ValueError(f"decision.location 无效（422）: {location}")

        merged_metadata = dict(metadata or {})
        # 合并 decision.metadata（若存在）
        dec_meta = _decision_field(decision, "metadata", {})
        if isinstance(dec_meta, dict):
            for k, v in dec_meta.items():
                merged_metadata.setdefault(k, v)

        try:
            if location == "memories":
                memory_id = self.write_memory(
                    content=content,
                    memory_type="long_term",
                    importance=3,
                    tags=merged_metadata.get("tags"),
                    metadata=merged_metadata,
                    permanent=False,
                    source=source or "user",
                )
                logger.info(f"write_with_decision → memories: memory_id={memory_id}")
                return {"location": "memories", "memory_id": memory_id, "rejected_id": None}

            if location == "permanent_memories":
                memory_id = self.write_permanent_memory(
                    content=content,
                    tags=merged_metadata.get("tags"),
                    metadata=merged_metadata,
                    source=source or "radix_decision",
                )
                logger.info(f"write_with_decision → permanent_memories: memory_id={memory_id}")
                return {
                    "location": "permanent_memories",
                    "memory_id": memory_id,
                    "rejected_id": None,
                }

            # location == "rejected" → 写入 rejected_content 表
            return self._write_rejected_content(content, decision, merged_metadata)
        except (ValueError, KeyError):
            raise
        except Exception as e:
            logger.error(f"write_with_decision 失败: {e}", exc_info=True)
            raise RuntimeError(f"write_with_decision 写入失败（500）: {e}") from e

    def _write_rejected_content(
        self,
        content: str,
        decision: Any,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """写入 rejected_content 表（write_with_decision 的 rejected 分支）。"""
        rejected_id = _new_uuid()
        session_id = _decision_field(decision, "session_id", "")
        quality_score = float(_decision_field(decision, "quality_score", 0.0))
        reject_reason = _decision_field(decision, "reason", "quality_score 低于阈值")
        decision_point = _decision_field(decision, "decision_point", "D6_REJECT")
        rubric_snapshot = _rubric_snapshot_to_dict(
            _decision_field(decision, "rubric_snapshot")
        )
        llm_reasoning = _decision_field(decision, "llm_reasoning")
        llm_confidence = _decision_field(decision, "llm_confidence")

        # 保留天数：优先 rubric_snapshot.rejected_content_retention_days，其次 metadata.retention_days
        retention_days = rubric_snapshot.get("rejected_content_retention_days", 30)
        if "retention_days" in metadata:
            try:
                retention_days = int(metadata["retention_days"])
            except (TypeError, ValueError):
                pass

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=int(retention_days))

        source_artifact_id = metadata.get("source_artifact_id")
        source_type = metadata.get("source_type")
        human_overridden = bool(
            _decision_field(decision, "override_decision") is not None
        )

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO rejected_content (
                    rejected_id, session_id, original_content,
                    source_artifact_id, source_type,
                    quality_score, reject_reason, decision_point,
                    rubric_snapshot, llm_reasoning, llm_confidence,
                    metadata, created_at, expires_at,
                    is_purged, purged_at, human_overridden
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rejected_id,
                    session_id,
                    content,
                    source_artifact_id,
                    source_type,
                    quality_score,
                    reject_reason,
                    decision_point,
                    json_dumps(rubric_snapshot, ensure_ascii=False),
                    llm_reasoning,
                    llm_confidence,
                    json_dumps(metadata, ensure_ascii=False),
                    now.isoformat(),
                    expires_at.isoformat(),
                    False,
                    None,
                    human_overridden,
                ),
            )
            conn.commit()
            logger.info(
                f"write_with_decision → rejected: rejected_id={rejected_id}, "
                f"session={session_id}, retention={retention_days}d"
            )
            return {
                "location": "rejected",
                "memory_id": None,
                "rejected_id": rejected_id,
            }
        except Exception as e:
            logger.error(f"写入 rejected_content 失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise RuntimeError(f"rejected_content 写入失败（500）: {e}") from e
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）

    def get_rejected_content(
        self,
        session_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """查询指定会话的被拒绝内容。

        Args:
            session_id: 会话 ID
            limit: 返回条数上限（默认 50）

        Returns:
            被拒绝内容记录列表（按 created_at 降序，不含已清理记录）

        Raises:
            KeyError: session_id 为空（404）
            RuntimeError: 查询失败（500）
        """
        if not session_id:
            raise KeyError("session_id 不能为空（404）")
        if limit <= 0:
            limit = 50

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT * FROM rejected_content
                WHERE session_id = ? AND is_purged = 0
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()
            results: List[Dict[str, Any]] = []
            for row in rows:
                record = self._row_to_rejected_content(row)
                results.append(record)
            return results
        except Exception as e:
            logger.error(f"查询 rejected_content 失败: {e}", exc_info=True)
            raise RuntimeError(f"rejected_content 查询失败（500）: {e}") from e
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）

    def cleanup_expired_rejected_content(
        self,
        retention_days: int = 30,
    ) -> int:
        """清理过期的被拒绝内容（标记 is_purged=True）。

        以 expires_at 为准：expires_at 早于当前时间的记录标记为已清理。
        retention_days 参数用于在没有 expires_at 时回退计算（兼容旧数据）。

        Args:
            retention_days: 保留天数（默认 30，仅在 expires_at 缺失时回退使用）

        Returns:
            清理的记录数量

        Raises:
            RuntimeError: 清理失败（500）
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        fallback_cutoff = (
            datetime.now(timezone.utc) - timedelta(days=int(retention_days))
        ).isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # 优先按 expires_at 清理；expires_at 为 NULL 时回退到 created_at + retention_days
            cursor.execute(
                """
                UPDATE rejected_content
                SET is_purged = 1, purged_at = ?
                WHERE is_purged = 0 AND (
                    (expires_at IS NOT NULL AND expires_at < ?)
                    OR
                    (expires_at IS NULL AND created_at < ?)
                )
                """,
                (now_iso, now_iso, fallback_cutoff),
            )
            purged_count = cursor.rowcount
            conn.commit()
            logger.info(
                f"清理过期 rejected_content: count={purged_count}, retention_days={retention_days}"
            )
            return purged_count
        except Exception as e:
            logger.error(f"清理 rejected_content 失败: {e}", exc_info=True)
            if conn:
                conn.rollback()
            raise RuntimeError(f"rejected_content 清理失败（500）: {e}") from e
        # M-D3: 连接所有权归 MemoryManager 连接池，此处不得 close（原 finally conn.close() 已移除）

    def _row_to_rejected_content(self, row: Any) -> Dict[str, Any]:
        """将数据库行转换为 rejected_content dict（对应 schema 字段）。"""
        try:
            rubric = json_loads(row["rubric_snapshot"]) if row["rubric_snapshot"] else {}
        except (ValueError, TypeError):
            rubric = {}
        try:
            meta = json_loads(row["metadata"]) if row["metadata"] else {}
        except (ValueError, TypeError):
            meta = {}
        return {
            "rejected_id": row["rejected_id"],
            "session_id": row["session_id"],
            "original_content": row["original_content"],
            "source_artifact_id": row["source_artifact_id"],
            "source_type": row["source_type"],
            "quality_score": row["quality_score"],
            "reject_reason": row["reject_reason"],
            "decision_point": row["decision_point"],
            "rubric_snapshot": rubric,
            "llm_reasoning": row["llm_reasoning"],
            "llm_confidence": row["llm_confidence"],
            "metadata": meta,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "is_purged": bool(row["is_purged"]),
            "purged_at": row["purged_at"],
            "human_overridden": bool(row["human_overridden"]),
        }
