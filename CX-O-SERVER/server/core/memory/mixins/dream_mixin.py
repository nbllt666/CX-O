"""MemoryManager mixin: 梦境记忆写入与生命周期（_DreamMixin，第 10 个 Mixin）。

CX-O-Dream 梦境引擎的记忆侧落点：以 type='dream' 软隔离写入 memories 表，
绝不污染真实记忆（红线 R1/R3）。

对应契约:
    - spec: .trae/specs/add-dream-engine-embedded/spec.md "梦境记忆写入与生命周期"
      / "MemoryManager Mixin 清单 +1"
    - decay_type='dream' 分支: server/core/memory/decay.py（本 Mixin 负责写入匹配的
      decay_params，如 {"alpha":1.0,"lambda1":0.8} pending / {"alpha":1.0,"lambda1":0.25} confirmed）
    - 不依赖 server.autonomy.dream.buffer（避免 core→autonomy 反向依赖；
      梦境本地拒绝记录由 autonomy 层 DreamConsolidator 处理）

@version 1.0.0
"""
from datetime import datetime
from typing import Dict, List, Optional

from ._common import json_dumps, json_loads, logger


class DreamIntegrityError(ValueError):
    """梦境记忆完整性断言失败。

    违反红线 R1/R3（permanent=TRUE / 缺 dream_session_id / source 非 dream_engine）
    时抛出，且不写入任何记录。
    """


class _DreamMixin:
    """梦境记忆写入与生命周期 mixin。

    提供 5 方法：
        - write_dream_memory(...): 写入梦境记忆（type='dream'）
        - consolidate_dream(...): pending/surfaced → confirmed 固化
        - reject_dream(...): 软删梦境记忆（type='dream'）
        - purge_dream_session(...): 按会话批量软删（红线 R5 回滚）
        - list_dreams(...): 按 consolidation_state 过滤查询
    """

    def write_dream_memory(
        self,
        content: str,
        dream_session_id: str,
        metadata: Optional[Dict] = None,
        agent_id: str = "default",
    ) -> int:
        """写入一条梦境记忆（type='dream'）。

        断言（违反抛 DreamIntegrityError 且不写入）：
            - metadata 必须含 dream_session_id 且等于参数
            - metadata.source == 'dream_engine'
            - permanent 必须为 False（参数/字段均不允许 True）

        强制落库字段：
            - metadata.is_ground_truth=False、consolidation_state='pending'、
              surfaced_at=None、confirmed_at=None
            - decay_type='dream'、decay_params={"alpha":1.0,"lambda1":0.8}
            - importance=1、importance_score=0.15、permanent=FALSE

        Args:
            content: 梦境记忆内容
            dream_session_id: 梦境会话 ID
            metadata: 元数据（必须含 dream_session_id 与 source='dream_engine'）
            agent_id: Agent ID，用于隔离不同 Agent 的记忆

        Returns:
            记忆ID

        Raises:
            DreamIntegrityError: 断言失败（不写入）
            RuntimeError: 数据库写入失败（500）
        """
        meta = dict(metadata or {})
        # 断言（红线 R1/R3）——不满足即抛错且不写入
        if meta.get("dream_session_id") != dream_session_id:
            raise DreamIntegrityError(
                "metadata.dream_session_id 必须存在且等于参数: "
                f"metadata={meta.get('dream_session_id')!r}, param={dream_session_id!r}"
            )
        if meta.get("source") != "dream_engine":
            raise DreamIntegrityError(
                f"metadata.source 必须为 'dream_engine': {meta.get('source')!r}"
            )
        if meta.get("permanent") is True:
            raise DreamIntegrityError("梦境记忆不允许 permanent=True（红线 R1）")

        # 强制字段（无论调用方传入什么）
        meta["is_ground_truth"] = False
        meta["consolidation_state"] = "pending"
        meta["surfaced_at"] = None
        meta["confirmed_at"] = None

        self._ensure_agent_table(agent_id)
        table_name = self._get_table_name(agent_id)

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"""
                INSERT INTO {table_name} (
                    type, content, source, importance, importance_score,
                    decay_type, decay_params, permanent,
                    metadata, created_at, agent_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "dream",
                    content,
                    "dream_engine",
                    1,
                    0.15,
                    "dream",
                    json_dumps({"alpha": 1.0, "lambda1": 0.8}),
                    False,
                    json_dumps(meta, ensure_ascii=False),
                    datetime.now().isoformat(),
                    agent_id,
                ),
            )
            memory_id = cursor.lastrowid

            content_preview = content if len(content) <= 100 else content[:100] + "…"
            cursor.execute(
                """
                INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    "create_dream",
                    memory_id,
                    dream_session_id,
                    "system",
                    json_dumps(
                        {
                            "content_preview": content_preview,
                            "agent_id": agent_id,
                            "dream_session_id": dream_session_id,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
            logger.info(
                f"梦境记忆已写入: id={memory_id}, session={dream_session_id}, agent={agent_id}"
            )
            return memory_id
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"写入梦境记忆失败: {e}", exc_info=True)
            raise RuntimeError(f"write_dream_memory 写入失败（500）: {e}") from e

    def consolidate_dream(
        self,
        memory_id: int,
        confirmed_importance: float = 0.4,
    ) -> bool:
        """固化梦境记忆（pending/surfaced → confirmed）。

        仅对 type='dream' 且 consolidation_state in (pending, surfaced) 生效；
        更新 importance_score=confirmed_importance、decay_params 放缓（λ=0.25）、
        metadata.consolidation_state='confirmed'、metadata.confirmed_at=now，
        并写 audit 'consolidate_dream'。

        Args:
            memory_id: 梦境记忆 ID
            confirmed_importance: 固化后的重要性分数（默认 0.4，对齐
                DreamConfig.confirmed_importance）

        Returns:
            是否固化成功（非梦境 / 状态不符 / 不存在时返回 False）
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT * FROM memories WHERE id = ? AND type = 'dream' AND is_deleted = FALSE",
                (memory_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return False

            try:
                meta = json_loads(row["metadata"] or "{}")
            except Exception:
                meta = {}
            if meta.get("consolidation_state") not in ("pending", "surfaced"):
                return False

            now_iso = datetime.now().isoformat()
            meta["consolidation_state"] = "confirmed"
            meta["confirmed_at"] = now_iso

            cursor.execute(
                """
                UPDATE memories
                SET importance_score = ?, metadata = ?, decay_params = ?, updated_at = ?
                WHERE id = ? AND type = 'dream' AND is_deleted = FALSE
            """,
                (
                    confirmed_importance,
                    json_dumps(meta, ensure_ascii=False),
                    json_dumps({"alpha": 1.0, "lambda1": 0.25}),
                    now_iso,
                    memory_id,
                ),
            )
            success = cursor.rowcount > 0
            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, operator, details)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        "consolidate_dream",
                        memory_id,
                        "system",
                        json_dumps(
                            {
                                "confirmed_importance": confirmed_importance,
                                "state": "confirmed",
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            conn.commit()
            return success
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"固化梦境记忆失败: {e}", exc_info=True)
            return False

    def reject_dream(self, memory_id: int, reason: str = "") -> bool:
        """否定并软删一条梦境记忆。

        仅对 type='dream' 生效：is_deleted=TRUE、deleted_at=now，并写 audit
        'reject_dream'（details 含 reason）。
        不写入共享 rejected_content 表，也不导入 server.autonomy.dream.buffer
        （避免 core→autonomy 反向依赖）；梦境本地拒绝记录由 autonomy 层
        DreamConsolidator 处理。

        Args:
            memory_id: 梦境记忆 ID
            reason: 否定原因（写入 audit details）

        Returns:
            是否软删成功
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            now_iso = datetime.now().isoformat()
            cursor.execute(
                """
                UPDATE memories
                SET is_deleted = TRUE, deleted_at = ?, updated_at = ?
                WHERE id = ? AND type = 'dream' AND is_deleted = FALSE
            """,
                (now_iso, now_iso, memory_id),
            )
            success = cursor.rowcount > 0
            if success:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, operator, details)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        "reject_dream",
                        memory_id,
                        "system",
                        json_dumps({"reason": reason}, ensure_ascii=False),
                    ),
                )
            conn.commit()
            return success
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"拒绝梦境记忆失败: {e}", exc_info=True)
            return False

    def purge_dream_session(
        self,
        dream_session_id: str,
        agent_id: str = "default",
    ) -> int:
        """按会话批量软删全部 type='dream' 记忆（红线 R5 回滚）。

        按 metadata.dream_session_id（json_extract）匹配，仅软删该会话
        未删除的梦境记忆，并逐条写 audit 'rollback_dream_session'。

        Args:
            dream_session_id: 梦境会话 ID
            agent_id: Agent ID

        Returns:
            软删的梦境记忆数量
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                f"""
                SELECT id FROM {table_name}
                WHERE type = 'dream' AND is_deleted = FALSE
                  AND json_extract(metadata, '$.dream_session_id') = ?
            """,
                (dream_session_id,),
            )
            ids = [row["id"] for row in cursor.fetchall()]
            if not ids:
                return 0

            now_iso = datetime.now().isoformat()
            placeholders = ",".join("?" for _ in ids)
            cursor.execute(
                f"""
                UPDATE {table_name}
                SET is_deleted = TRUE, deleted_at = ?, updated_at = ?
                WHERE id IN ({placeholders}) AND type = 'dream' AND is_deleted = FALSE
            """,
                [now_iso, now_iso] + ids,
            )
            purged = cursor.rowcount

            for mid in ids:
                cursor.execute(
                    """
                    INSERT INTO audit_logs (operation, memory_id, session_id, operator, details)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        "rollback_dream_session",
                        mid,
                        dream_session_id,
                        "system",
                        json_dumps(
                            {
                                "agent_id": agent_id,
                                "dream_session_id": dream_session_id,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
            conn.commit()
            logger.info(
                f"梦境会话回滚: session={dream_session_id}, purged={purged}, agent={agent_id}"
            )
            return purged
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"梦境会话回滚失败: {e}", exc_info=True)
            return 0

    def list_dreams(
        self,
        agent_id: str = "default",
        state: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """列出梦境记忆（type='dream'，不含软删）。

        Args:
            agent_id: Agent ID
            state: 按 consolidation_state 过滤（pending/surfaced/confirmed），None 不过滤
            limit: 返回条数上限（默认 50）

        Returns:
            梦境记忆列表（created_at DESC）
        """
        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            conditions = ["type = 'dream'", "is_deleted = FALSE"]
            params: List = []
            if state:
                conditions.append("json_extract(metadata, '$.consolidation_state') = ?")
                params.append(state)
            params.append(limit)

            cursor.execute(
                f"""
                SELECT * FROM {table_name}
                WHERE {" AND ".join(conditions)}
                ORDER BY created_at DESC
                LIMIT ?
            """,
                params,
            )
            rows = cursor.fetchall()
            return [self._row_to_memory(row) for row in rows]
        except Exception as e:
            logger.error(f"列出梦境记忆失败: {e}", exc_info=True)
            return []
