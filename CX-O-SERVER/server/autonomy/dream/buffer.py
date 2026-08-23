"""CX-O-Dream 梦境缓冲隔离（红线 R5 前置）。

固化前的梦境候选只进此缓冲，**不直接进主库**；用户否定时
`decision='rejected'` + `decision_reason`，保留 30 天审计后可清
（梦境本地拒绝记录，不写共享 rejected_content 表，见 spec Frozen Decision 5）。

- 独立 SQLite 文件 data/dream_buffer.db（基于 __file__ 绝对路径解析，禁止相对路径）
- 连接采用"每操作短连接"模式（对齐 server/core/session/store.py），线程安全
- 表 dream_buffer 与主库（memories）完全隔离，绝不污染真实记忆
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.autonomy.dream.config import DreamConfig

# 合法决策值（对齐 spec：pending / approved / rejected）
_DECISIONS = ("pending", "approved", "rejected")

# rejected 后默认保留审计天数
_REJECT_RETENTION_DAYS = 30

# 数据目录：本文件位于 server/autonomy/dream/ 下，向上两级即 server/autonomy/，
# 数据目录为 server/autonomy/data/（对齐 config.resolve_store_dir）。
_DEFAULT_DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "dream_buffer.db")


def _dump_json(value: Any) -> Optional[str]:
    """JSON 字段序列化：None 存 NULL，字符串原样，其余 json.dumps。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _load_json(value: Any) -> Any:
    """JSON 字段反序列化：NULL 返回 None，解析失败原样返回。"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


class DreamBuffer:
    """梦境候选缓冲——固化前的梦境候选隔离存储。

    独立 SQLite 文件，与主库完全隔离。每个公开方法使用独立的短连接，
    操作完成后立即关闭（对齐 session/store.py），天然线程安全。
    """

    def __init__(self, db_path: str = "", config: Optional[DreamConfig] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.config = config or DreamConfig()
        self._init_db()

    # -------------------------------------------------------------- 连接与初始化
    def _connect(self) -> sqlite3.Connection:
        """新建短连接（每操作一次，操作完由调用方关闭）。"""
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化数据库表（幂等，可重复调用）。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dream_buffer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dream_session_id VARCHAR(64) NOT NULL,
                    agent_id VARCHAR(100) DEFAULT 'default',
                    candidate_content TEXT NOT NULL,
                    associated_memories TEXT,
                    associated_entities TEXT,
                    lucidity_score FLOAT DEFAULT 0.0,
                    emotion_shift TEXT,
                    decision VARCHAR(20) DEFAULT 'pending',
                    decision_reason TEXT,
                    created_at TIMESTAMP,
                    expires_at TIMESTAMP
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    # -------------------------------------------------------------- 行转字典
    def _row_to_dict(self, row) -> Dict[str, Any]:
        """将数据库行转换为字典（JSON 字段反序列化）。"""
        return {
            "id": row["id"],
            "dream_session_id": row["dream_session_id"],
            "agent_id": row["agent_id"],
            "candidate_content": row["candidate_content"],
            "associated_memories": _load_json(row["associated_memories"]),
            "associated_entities": _load_json(row["associated_entities"]),
            "lucidity_score": row["lucidity_score"],
            "emotion_shift": _load_json(row["emotion_shift"]),
            "decision": row["decision"],
            "decision_reason": row["decision_reason"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
        }

    # -------------------------------------------------------------- 写入
    def put(self, candidate: dict) -> int:
        """候选入缓冲：写入 decision='pending'，expires_at=created_at+ttl_hours。

        candidate 字段：dream_session_id / agent_id / candidate_content /
        associated_memories / associated_entities / lucidity_score / emotion_shift。
        返回新记录 id。
        """
        now = datetime.now()
        expires_at = now + timedelta(hours=self.config.dream_ttl_hours)
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO dream_buffer (
                    dream_session_id, agent_id, candidate_content,
                    associated_memories, associated_entities, lucidity_score,
                    emotion_shift, decision, decision_reason, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(candidate.get("dream_session_id") or ""),
                    str(candidate.get("agent_id") or "default"),
                    str(candidate.get("candidate_content") or ""),
                    _dump_json(candidate.get("associated_memories")),
                    _dump_json(candidate.get("associated_entities")),
                    float(candidate.get("lucidity_score") or 0.0),
                    _dump_json(candidate.get("emotion_shift")),
                    "pending",
                    None,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    # -------------------------------------------------------------- 查询
    def list(
        self,
        agent_id: str = "default",
        decision: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """按 agent（默认 default）列出缓冲候选，按 created_at DESC，可过滤 decision。"""
        query = "SELECT * FROM dream_buffer WHERE agent_id = ?"
        params: List[Any] = [agent_id]
        if decision is not None:
            query += " AND decision = ?"
            params.append(decision)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        conn = self._connect()
        try:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    def count(
        self,
        agent_id: str = "default",
        decision: Optional[str] = None,
    ) -> int:
        """按 agent（默认 default）统计缓冲候选总匹配数，可过滤 decision（供分页 total 使用）。"""
        query = "SELECT COUNT(*) FROM dream_buffer WHERE agent_id = ?"
        params: List[Any] = [agent_id]
        if decision is not None:
            query += " AND decision = ?"
            params.append(decision)

        conn = self._connect()
        try:
            row = conn.execute(query, params).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def get(self, buffer_id: int) -> Optional[Dict[str, Any]]:
        """按 id 查询缓冲候选，不存在返回 None。"""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM dream_buffer WHERE id = ?", (buffer_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            conn.close()

    def get_by_session(self, dream_session_id: str) -> List[Dict[str, Any]]:
        """按梦境会话查询缓冲候选（全部 decision），按 created_at DESC。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM dream_buffer WHERE dream_session_id = ?
                ORDER BY created_at DESC
                """,
                (dream_session_id,),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            conn.close()

    # -------------------------------------------------------------- 决策
    def mark_decision(
        self,
        buffer_id: int,
        decision: str,
        reason: str = "",
        retention_days: Optional[int] = None,
    ) -> bool:
        """标记决策：decision ∈ pending/approved/rejected。

        - rejected：expires_at = now + retention_days（默认 30 天，保留审计）
        - approved/pending：不改 expires_at
        返回是否命中记录。
        """
        if decision not in _DECISIONS:
            raise ValueError(f"decision 非法值 {decision!r}，可选 pending/approved/rejected")

        conn = self._connect()
        try:
            cursor = conn.cursor()
            if decision == "rejected":
                days = (
                    retention_days
                    if retention_days is not None
                    else _REJECT_RETENTION_DAYS
                )
                expires_at = datetime.now() + timedelta(days=days)
                cursor.execute(
                    """
                    UPDATE dream_buffer
                    SET decision = ?, decision_reason = ?, expires_at = ?
                    WHERE id = ?
                    """,
                    (decision, reason, expires_at.isoformat(), buffer_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE dream_buffer
                    SET decision = ?, decision_reason = ?
                    WHERE id = ?
                    """,
                    (decision, reason, buffer_id),
                )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # -------------------------------------------------------------- 清理
    def purge_expired(self, now: Optional[datetime] = None) -> int:
        """删除 expires_at 已过期的缓冲候选，返回删除数。"""
        now = now or datetime.now()
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM dream_buffer
                WHERE expires_at IS NOT NULL AND expires_at < ?
                """,
                (now.isoformat(),),
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()
