"""
server/storage/database/migrations.py 回归测试
用真实临时 SQLite 库执行迁移，验证建表与索引
"""
import asyncio

import pytest

from server.storage.database.migrations import run_migrations

EXPECTED_TABLES = {
    "memories",
    "sessions",
    "messages",
    "audit_logs",
    "permanent_memories",
    "acp_agents",
    "acp_connections",
    "acp_groups",
    "acp_messages",
    "agent_contexts",
    "agent_context_messages",
    "agent_memory_tables",
}

# 迁移中声明的索引（不完全枚举，抽取代表性索引验证）
EXPECTED_INDEXES = {
    "idx_memories_type",
    "idx_memories_created_at",
    "idx_messages_session",
    "idx_acp_agents_status",
    "idx_audit_logs_operation",
    "idx_permanent_memories_created",
    "idx_agent_contexts_agent_id",
}


@pytest.mark.asyncio
async def test_run_migrations_creates_all_tables(tmp_path):
    db_path = str(tmp_path / "mig.db")
    await run_migrations(db_path)

    import aiosqlite

    conn = await aiosqlite.connect(db_path)
    try:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in await cursor.fetchall()}
    finally:
        await conn.close()

    assert EXPECTED_TABLES <= tables


@pytest.mark.asyncio
async def test_run_migrations_creates_indexes(tmp_path):
    db_path = str(tmp_path / "mig_idx.db")
    await run_migrations(db_path)

    import aiosqlite

    conn = await aiosqlite.connect(db_path)
    try:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        indexes = {row[0] for row in await cursor.fetchall()}
    finally:
        await conn.close()

    assert EXPECTED_INDEXES <= indexes


@pytest.mark.asyncio
async def test_run_migrations_idempotent(tmp_path):
    """重复执行迁移不报错、不重复建表。"""
    db_path = str(tmp_path / "mig_idem.db")
    await run_migrations(db_path)
    await run_migrations(db_path)  # 应为幂等，不抛异常

    import aiosqlite

    conn = await aiosqlite.connect(db_path)
    try:
        cursor = await conn.cursor()
        await cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in await cursor.fetchall()}
    finally:
        await conn.close()

    assert EXPECTED_TABLES <= tables


@pytest.mark.asyncio
async def test_run_migrations_creates_schema_columns(tmp_path):
    """抽查 memories 表关键列存在，验证 schema 落库。"""
    db_path = str(tmp_path / "mig_cols.db")
    await run_migrations(db_path)

    import aiosqlite

    conn = await aiosqlite.connect(db_path)
    try:
        cursor = await conn.cursor()
        await cursor.execute("PRAGMA table_info(memories)")
        cols = {row[1] for row in await cursor.fetchall()}
    finally:
        await conn.close()

    assert {"id", "type", "content", "importance_score", "permanent", "is_deleted"} <= cols