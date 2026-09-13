"""MemoryManager mixin: 评测支撑操作（时间旅行回拨等，仅供评测框架使用）。

新增于评测支撑需求：为外部评测框架提供记忆时间整体回拨能力，
模拟记忆长期劣化场景。此 mixin 不参与常规业务写入路径。
"""
import json
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, TYPE_CHECKING


from ._common import logger

if TYPE_CHECKING:
    pass


class _EvalMixin:
    """评测支撑 mixin：时间旅行回拨（仅供外部评测框架调用）。"""

    @staticmethod
    def _shift_timestamp_str(value, delta: timedelta):
        """将时间戳字符串减去 delta，返回与库内写入格式一致的 isoformat 字符串。

        库内时间戳由 write_memory 以 datetime.now().isoformat() 写入
        （含微秒、T 分隔符）；对 NULL/空值原样返回（不虚构时间）。
        兼容 SQLite CURRENT_TIMESTAMP 的空格分隔格式与 Z 后缀。
        """
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return value
        normalized = text.replace("Z", "+00:00")
        if " " in normalized:
            normalized = normalized.replace(" ", "T", 1)
        dt = datetime.fromisoformat(normalized)
        return (dt - delta).isoformat()

    def shift_memory_time(
        self,
        agent_id: str,
        shift_days: int,
        memory_ids: Optional[List[int]] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        """将该 agent 下未删除记忆的 created_at/updated_at 整体回拨 shift_days 天。

        仅供评测框架对专用 eval agent 使用，用于模拟记忆长期劣化。
        所有回拨在同一 SQLite 连接事务内完成，逐条 UPDATE 后单次 commit，
        任一条失败整体 rollback（无部分写入）。

        Args:
            agent_id: Agent 唯一标识。必填，为空/None 时抛 ValueError
                （禁止全库回拨）。
            shift_days: 回拨天数（正整数）。由调用方保证 1..3650 范围，
                此处仅防御非正数。
            memory_ids: 可选，仅回拨指定 id 的记忆。
            tags: 可选，仅回拨 tags 含任一给定标签的记忆（JSON 数组匹配，
                与 batch_update_tags 的解析容错口径一致）。

        Returns:
            实际回拨的记忆条数 shifted_count。

        Raises:
            ValueError: agent_id 为空/None，或 shift_days 非正整数。
        """
        if not agent_id or not str(agent_id).strip():
            raise ValueError("agent_id 不能为空：时间旅行回拨必须指定目标 agent，禁止全库回拨")
        if not isinstance(shift_days, int) or isinstance(shift_days, bool) or shift_days <= 0:
            raise ValueError(f"shift_days 必须为正整数，收到: {shift_days!r}")

        table_name = self._get_table_name(agent_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # agent 专属表不存在视为无记忆（返回 0，由路由层映射 404）
            if table_name != "memories":
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table_name,),
                )
                if cursor.fetchone() is None:
                    return 0

            query = f"SELECT id, tags, created_at, updated_at FROM {table_name} WHERE is_deleted = 0"
            params: list = []
            if memory_ids:
                ids = [int(mid) for mid in memory_ids]
                if not ids:
                    return 0
                query += f" AND id IN ({','.join('?' * len(ids))})"
                params.extend(ids)

            rows = cursor.execute(query, params).fetchall()

            target_tags = set(tags or [])
            delta = timedelta(days=shift_days)
            shifted_count = 0
            vector_shifts: dict = {}

            for row in rows:
                memory_id, tags_json, created_at, updated_at = (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                )

                if target_tags:
                    try:
                        row_tags = set(json.loads(tags_json)) if tags_json else set()
                    except (TypeError, ValueError):
                        row_tags = set()
                    if not target_tags.intersection(row_tags):
                        continue

                new_created = self._shift_timestamp_str(created_at, delta)
                new_updated = self._shift_timestamp_str(updated_at, delta)
                cursor.execute(
                    f"UPDATE {table_name} SET created_at = ?, updated_at = ? WHERE id = ?",
                    (new_created, new_updated, memory_id),
                )
                vector_shifts[str(memory_id)] = new_created
                shifted_count += 1

            conn.commit()
            logger.info(
                f"时间旅行回拨完成: agent={agent_id}, shift_days={shift_days}, "
                f"shifted={shifted_count}, ids={bool(memory_ids)}, tags={sorted(target_tags) if target_tags else None}"
            )

            # 向量侧同步回拨：hybrid 向量检索（主通道）的时间来源是 Weaviate payload
            # 的 created_at，不同步回拨会让时间衰减通道失效——该忘的记忆永远忘不掉
            # （memory_decay 评测 100% 保持的根因，2026-09-12）。SQLite 失败时不会
            # 走到这里；向量侧失败仅记录不阻断（SQLite 是 source of truth）。
            if vector_shifts and getattr(self, "_vector_store", None):
                try:
                    shifted_vec = self._run_async_sync(
                        self._vector_store.shift_created_at(vector_shifts, agent_id=agent_id)
                    )
                    logger.info(
                        f"向量侧 created_at 回拨完成: agent={agent_id}, shifted={shifted_vec}"
                    )
                except Exception as e:
                    logger.error(
                        f"向量侧 created_at 回拨失败（SQLite 已回拨成功）: agent={agent_id}, error={e}",
                        exc_info=True,
                    )

            return shifted_count
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"时间旅行回拨失败: agent={agent_id}, error={e}", exc_info=True)
            raise
