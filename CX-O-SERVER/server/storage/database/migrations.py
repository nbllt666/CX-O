import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def run_migrations(db_path: str = "data/memories.db"):
    logger.info("开始执行数据库迁移...")

    import aiosqlite

    conn = await aiosqlite.connect(db_path)
    cursor = await conn.cursor()

    migrations = [
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            vector_id VARCHAR(100),
            metadata TEXT,
            importance INTEGER DEFAULT 3,
            importance_score FLOAT DEFAULT 0.6,
            decay_type VARCHAR(20) DEFAULT 'exponential',
            decay_params TEXT,
            reactivation_count INTEGER DEFAULT 0,
            emotion_score FLOAT DEFAULT 0.0,
            permanent BOOLEAN DEFAULT FALSE,
            psychological_age FLOAT DEFAULT 1.0,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            archived_at TIMESTAMP,
            is_deleted BOOLEAN DEFAULT FALSE,
            source VARCHAR(50) DEFAULT 'user',
            workspace_id VARCHAR(100) DEFAULT 'default'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sessions (
            id VARCHAR(36) PRIMARY KEY,
            workspace_id VARCHAR(100) DEFAULT 'default',
            title VARCHAR(500),
            user_id VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            message_count INTEGER DEFAULT 0,
            summary TEXT,
            metadata TEXT,
            is_active BOOLEAN DEFAULT TRUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            id VARCHAR(36) PRIMARY KEY,
            session_id VARCHAR(36) NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            content_type VARCHAR(20) DEFAULT 'text',
            metadata TEXT,
            tokens INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_deleted BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation VARCHAR(50) NOT NULL,
            memory_id INTEGER,
            session_id VARCHAR(36),
            memory_type VARCHAR(20),
            operator VARCHAR(20) NOT NULL,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS permanent_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            vector_id VARCHAR(100),
            metadata TEXT,
            importance_score FLOAT DEFAULT 1.0,
            emotion_score FLOAT DEFAULT 0.0,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            source VARCHAR(50) DEFAULT 'user',
            verified BOOLEAN DEFAULT TRUE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS acp_agents (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            host VARCHAR(100) NOT NULL,
            port INTEGER NOT NULL,
            status VARCHAR(20) DEFAULT 'offline',
            version VARCHAR(50) DEFAULT '1.0.0',
            capabilities TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS acp_connections (
            id VARCHAR(36) PRIMARY KEY,
            local_agent_id VARCHAR(36) NOT NULL,
            remote_agent_id VARCHAR(36) NOT NULL,
            remote_agent_name VARCHAR(200),
            host VARCHAR(100) NOT NULL,
            port INTEGER NOT NULL,
            status VARCHAR(20) DEFAULT 'disconnected',
            connected_at TIMESTAMP,
            last_activity TIMESTAMP,
            messages_sent INTEGER DEFAULT 0,
            messages_received INTEGER DEFAULT 0,
            metadata TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS acp_groups (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            description TEXT,
            creator_id VARCHAR(36) NOT NULL,
            creator_name VARCHAR(200),
            members TEXT,
            max_members INTEGER DEFAULT 50,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS acp_messages (
            id VARCHAR(36) PRIMARY KEY,
            type VARCHAR(50) NOT NULL,
            from_agent_id VARCHAR(36) NOT NULL,
            from_agent_name VARCHAR(200),
            to_agent_id VARCHAR(36),
            to_group_id VARCHAR(36),
            content TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_read BOOLEAN DEFAULT FALSE,
            is_sent BOOLEAN DEFAULT FALSE,
            metadata TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id VARCHAR(100) NOT NULL UNIQUE,
            session_id VARCHAR(36),
            context_data TEXT,
            memory_state TEXT,
            last_active TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_context_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS agent_memory_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id VARCHAR(100) NOT NULL UNIQUE,
            table_name VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
        """,
    ]

    for i, migration in enumerate(migrations):
        try:
            await cursor.execute(migration)
            logger.info(f"迁移 {i+1} 执行成功")
        except Exception as e:
            logger.warning(f"迁移 {i+1} 失败或已存在: {e}")

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type)",
        "CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_memories_is_deleted ON memories(is_deleted)",
        "CREATE INDEX IF NOT EXISTS idx_memories_permanent ON memories(permanent)",
        "CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)",
        "CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_workspace ON sessions(workspace_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at)",
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_acp_agents_status ON acp_agents(status)",
        "CREATE INDEX IF NOT EXISTS idx_acp_connections_status ON acp_connections(status)",
        "CREATE INDEX IF NOT EXISTS idx_acp_groups_active ON acp_groups(is_active)",
        "CREATE INDEX IF NOT EXISTS idx_acp_messages_read ON acp_messages(is_read)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_operation ON audit_logs(operation)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_permanent_memories_created ON permanent_memories(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_permanent_memories_importance_score ON permanent_memories(importance_score)",
        "CREATE INDEX IF NOT EXISTS idx_agent_contexts_agent_id ON agent_contexts(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_context_messages_agent_id ON agent_context_messages(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_memory_tables_agent_id ON agent_memory_tables(agent_id)",
    ]

    for idx_sql in indexes:
        try:
            await cursor.execute(idx_sql)
        except Exception as e:
            logger.warning(f"索引创建失败或已存在: {e}")

    await conn.commit()
    await conn.close()

    logger.info("数据库迁移完成")
