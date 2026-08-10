import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from server.core.logging_config import get_contextual_logger

try:
    import orjson

    def json_dumps(obj, **kwargs):
        return orjson.dumps(obj).decode("utf-8")

    def json_loads(s, **kwargs):
        return orjson.loads(s)

except ImportError:
    import json

    def json_dumps(obj, **kwargs):
        return json.dumps(obj, **kwargs)

    def json_loads(s, **kwargs):
        return json.loads(s, **kwargs)


logger = get_contextual_logger(__name__)


class AsyncMemoryManager:
    """异步记忆管理器
    
    负责记忆的创建、查询、更新、删除等操作，支持向量搜索和混合搜索
    所有数据库操作均为异步
    """

    def __init__(self, db_path: str = "data/memories.db", vector_size: int = 768):
        self.db_path = db_path
        self.vector_size = vector_size
        self._pool: Optional[aiosqlite.Connection] = None
        self._pool_lock = asyncio.Lock()
        self._initialized = False
        
    async def initialize(self):
        """初始化数据库连接池"""
        async with self._pool_lock:
            await self._init_connection()

    async def _init_db(self):
        """初始化数据库表结构"""
        cursor = await self._pool.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
        table_exists = await cursor.fetchone()
        
        if not table_exists:
            await self._pool.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'short_term',
                    importance INTEGER NOT NULL DEFAULT 3,
                    tags TEXT,
                    metadata TEXT,
                    permanent INTEGER NOT NULL DEFAULT 0,
                    emotion_score REAL NOT NULL DEFAULT 0.0,
                    workspace_id TEXT NOT NULL DEFAULT 'default',
                    agent_id TEXT NOT NULL DEFAULT 'default',
                    vector_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    accessed_at TEXT NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    decay_score REAL NOT NULL DEFAULT 0.0,
                    is_deleted INTEGER NOT NULL DEFAULT 0
                )
            """)
            
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories(workspace_id)",
                "CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id)",
                "CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type)",
                "CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance)",
                "CREATE INDEX IF NOT EXISTS idx_memories_permanent ON memories(permanent)",
                "CREATE INDEX IF NOT EXISTS idx_memories_vector ON memories(vector_id)",
                "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_memories_accessed ON memories(accessed_at)",
            ]
            for idx in indexes:
                await self._pool.execute(idx)
            
            await self._pool.execute(
                """
                CREATE TABLE IF NOT EXISTS permanent_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vector_id VARCHAR(100),
                    content TEXT NOT NULL,
                    importance_score FLOAT DEFAULT 1.0,
                    emotion_score FLOAT DEFAULT 0.0,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    metadata TEXT,
                    source VARCHAR(50) DEFAULT 'user',
                    verified BOOLEAN DEFAULT TRUE
                )
                """
            )
            
            await self._pool.commit()
            logger.info("数据库表结构初始化完成")

    async def _get_connection(self) -> aiosqlite.Connection:
        """获取数据库连接"""
        async with self._pool_lock:
            if not self._initialized:
                await self._init_connection()
            return self._pool

    async def _init_connection(self):
        """内部初始化连接方法（需要在锁内调用）"""
        if self._initialized:
            return
            
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._pool = await aiosqlite.connect(
            self.db_path, 
            timeout=30.0
        )
        self._pool.row_factory = aiosqlite.Row
        await self._pool.execute("PRAGMA journal_mode=WAL")
        await self._pool.execute("PRAGMA synchronous=NORMAL")
        await self._pool.execute("PRAGMA cache_size=-64000")
        await self._pool.execute("PRAGMA temp_store=MEMORY")
        await self._pool.execute("PRAGMA mmap_size=268435456")
        await self._pool.execute("PRAGMA busy_timeout=30000")
        
        await self._init_db()
        self._initialized = True
        logger.info(f"AsyncMemoryManager 初始化完成: {self.db_path}")

    async def write_memory(
        self,
        content: str,
        memory_type: str = "short_term",
        importance: int = 3,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        permanent: bool = False,
        emotion_score: float = 0.0,
        workspace_id: str = "default",
        agent_id: str = "default",
    ) -> int:
        """异步写入记忆
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型（long_term, short_term, permanent）
            importance: 重要性等级（1-5）
            tags: 标签列表
            metadata: 元数据
            permanent: 是否为永久记忆
            emotion_score: 情感分数
            workspace_id: 工作区ID
            agent_id: Agent ID
            
        Returns:
            记忆ID
        """
        conn = await self._get_connection()
        
        now = datetime.now().isoformat()
        tags_json = json_dumps(tags or [])
        metadata_json = json_dumps(metadata or {})
        
        cursor = await conn.execute(
            """
            INSERT INTO memories (
                content, memory_type, importance, tags, metadata, permanent,
                emotion_score, workspace_id, agent_id, created_at, updated_at,
                accessed_at, access_count, decay_score, is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (content, memory_type, importance, tags_json, metadata_json, 
             1 if permanent else 0, emotion_score, workspace_id, agent_id,
             now, now, now, 0, 0.0, 0)
        )
        await conn.commit()
        memory_id = cursor.lastrowid
        
        logger.debug(f"写入记忆成功: ID={memory_id}, type={memory_type}")
        return memory_id

    async def get_memory(self, memory_id: int, include_deleted: bool = False) -> Optional[Dict]:
        """异步获取单条记忆
        
        Args:
            memory_id: 记忆ID
            include_deleted: 是否包含已删除的记忆
            
        Returns:
            记忆字典，不存在则返回None
        """
        conn = await self._get_connection()
        
        query = "SELECT * FROM memories WHERE id = ?"
        if not include_deleted:
            query += " AND is_deleted = 0"
            
        cursor = await conn.execute(query, (memory_id,))
        row = await cursor.fetchone()
        
        if row:
            return self._row_to_memory(row)
        return None

    async def search_memories(
        self,
        workspace_id: str = "default",
        agent_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        importance: Optional[int] = None,
        tags: Optional[List[str]] = None,
        keywords: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> List[Dict]:
        """异步搜索记忆
        
        Args:
            workspace_id: 工作区ID
            agent_id: Agent ID筛选
            memory_type: 记忆类型筛选
            importance: 重要性等级筛选
            tags: 标签筛选
            keywords: 关键词搜索
            limit: 返回数量限制
            offset: 偏移量
            include_deleted: 是否包含已删除的记忆
            
        Returns:
            记忆列表
        """
        conn = await self._get_connection()
        
        conditions = ["workspace_id = ?"]
        params: List[Any] = [workspace_id]
        
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
            
        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type)
            
        if importance:
            conditions.append("importance >= ?")
            params.append(importance)
            
        if tags:
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
                
        if keywords:
            conditions.append("content LIKE ?")
            params.append(f"%{keywords}%")
            
        if not include_deleted:
            conditions.append("is_deleted = 0")
            
        where_clause = " AND ".join(conditions)
        
        query = f"""
            SELECT * FROM memories
            WHERE {where_clause}
            ORDER BY importance DESC, accessed_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        
        return [self._row_to_memory(row) for row in rows]

    async def update_memory(
        self,
        memory_id: int,
        content: Optional[str] = None,
        memory_type: Optional[str] = None,
        importance: Optional[int] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
        permanent: Optional[bool] = None,
        emotion_score: Optional[float] = None,
    ) -> bool:
        """异步更新记忆
        
        Args:
            memory_id: 记忆ID
            content: 新内容
            memory_type: 新类型
            importance: 新重要性
            tags: 新标签
            metadata: 新元数据
            permanent: 永久记忆
            emotion_score: 情感分数
            
        Returns:
            是否成功
        """
        conn = await self._get_connection()
        
        updates = []
        params: List[Any] = []
        
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if memory_type is not None:
            updates.append("memory_type = ?")
            params.append(memory_type)
        if importance is not None:
            updates.append("importance = ?")
            params.append(importance)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json_dumps(tags))
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json_dumps(metadata))
        if permanent is not None:
            updates.append("permanent = ?")
            params.append(1 if permanent else 0)
        if emotion_score is not None:
            updates.append("emotion_score = ?")
            params.append(emotion_score)
            
        if not updates:
            return False
            
        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(memory_id)
        
        query = f"UPDATE memories SET {', '.join(updates)} WHERE id = ?"
        
        cursor = await conn.execute(query, params)
        await conn.commit()
        
        return cursor.rowcount > 0

    async def delete_memory(self, memory_id: int, hard: bool = False) -> bool:
        """异步删除记忆
        
        Args:
            memory_id: 记忆ID
            hard: 是否物理删除
            
        Returns:
            是否成功
        """
        conn = await self._get_connection()
        
        if hard:
            cursor = await conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        else:
            cursor = await conn.execute(
                "UPDATE memories SET is_deleted = 1, updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), memory_id)
            )
            
        await conn.commit()
        return cursor.rowcount > 0

    async def batch_write_memories(self, memories: List[Dict]) -> Dict:
        """异步批量写入记忆
        
        Args:
            memories: 记忆列表
            
        Returns:
            结果统计
        """
        conn = await self._get_connection()
        
        now = datetime.now().isoformat()
        success = 0
        failed = 0
        errors = []
        
        for mem in memories:
            try:
                tags = mem.get("tags", [])
                metadata = mem.get("metadata", {})
                
                await conn.execute(
                    """
                    INSERT INTO memories (
                        content, memory_type, importance, tags, metadata, permanent,
                        emotion_score, workspace_id, agent_id, created_at, updated_at,
                        accessed_at, access_count, decay_score, is_deleted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (mem.get("content", ""),
                     mem.get("memory_type", "short_term"),
                     mem.get("importance", 3),
                     json_dumps(tags),
                     json_dumps(metadata),
                     1 if mem.get("permanent", False) else 0,
                     mem.get("emotion_score", 0.0),
                     mem.get("workspace_id", "default"),
                     mem.get("agent_id", "default"),
                     now, now, now, 0, 0.0, 0)
                )
                success += 1
            except Exception as e:
                failed += 1
                errors.append(str(e))
                
        await conn.commit()
        
        logger.info(f"批量写入完成: success={success}, failed={failed}")
        return {"success": success, "failed": failed, "errors": errors}

    async def get_memory_statistics(self, workspace_id: str = "default") -> Dict:
        """异步获取记忆统计
        
        Args:
            workspace_id: 工作区ID
            
        Returns:
            统计信息
        """
        conn = await self._get_connection()
        
        cursor = await conn.execute(
            "SELECT COUNT(*) as total FROM memories WHERE workspace_id = ? AND is_deleted = 0",
            (workspace_id,)
        )
        total = (await cursor.fetchone())[0]
        
        cursor = await conn.execute(
            "SELECT memory_type, COUNT(*) as count FROM memories WHERE workspace_id = ? AND is_deleted = 0 GROUP BY memory_type",
            (workspace_id,)
        )
        type_counts = {row[0]: row[1] for row in await cursor.fetchall()}
        
        cursor = await conn.execute(
            "SELECT AVG(importance) as avg_importance FROM memories WHERE workspace_id = ? AND is_deleted = 0",
            (workspace_id,)
        )
        avg_importance = (await cursor.fetchone())[0] or 0
        
        return {
            "total": total,
            "by_type": type_counts,
            "avg_importance": round(avg_importance, 2)
        }

    def _row_to_memory(self, row: aiosqlite.Row) -> Dict:
        """将数据库行转换为记忆字典"""
        return {
            "id": row["id"],
            "content": row["content"],
            "memory_type": row["memory_type"],
            "importance": row["importance"],
            "tags": json_loads(row["tags"]) if row["tags"] else [],
            "metadata": json_loads(row["metadata"]) if row["metadata"] else {},
            "permanent": bool(row["permanent"]),
            "emotion_score": row["emotion_score"],
            "workspace_id": row["workspace_id"],
            "agent_id": row["agent_id"],
            "vector_id": row["vector_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "accessed_at": row["accessed_at"],
            "access_count": row["access_count"],
            "decay_score": row["decay_score"],
            "is_deleted": bool(row["is_deleted"]),
        }

    async def is_vector_search_enabled(self) -> bool:
        """检查向量搜索是否启用"""
        return False

    async def hybrid_search(
        self,
        query: str,
        memory_type: str = None,
        tags: List[str] = None,
        limit: int = 10,
        workspace_id: str = None,
    ) -> List[Dict]:
        """混合搜索（向量+关键词）"""
        return await self.search_memories(
            keywords=query,
            memory_type=memory_type,
            tags=tags,
            limit=limit,
            workspace_id=workspace_id or "default"
        )

    async def search_memories_3d(
        self,
        query: str,
        limit: int = 10,
        workspace_id: str = "default",
        agent_id: str = None,
    ) -> List[Dict]:
        """3D搜索记忆"""
        return await self.search_memories(
            keywords=query,
            limit=limit,
            workspace_id=workspace_id,
            agent_id=agent_id
        )

    async def recall_memory(
        self, memory_id: int, emotion_intensity: float = 0.0
    ) -> Optional[Dict]:
        """回忆记忆"""
        memory = await self.get_memory(memory_id)
        if memory:
            memory["emotion_intensity"] = emotion_intensity
        return memory

    async def write_permanent_memory(
        self,
        content: str,
        tags: List[str] = None,
        metadata: Dict = None,
        emotion_score: float = 0.0,
        source: str = "user",
        is_from_main: bool = True,
    ) -> int:
        """写入永久记忆"""
        conn = await self._get_connection()
        
        cursor = await conn.execute(
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
                json_dumps(tags or []),
                json_dumps(metadata or {}),
                datetime.now().isoformat(),
                source,
                0,
            )
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_permanent_memory(self, memory_id: int) -> Optional[Dict]:
        """获取永久记忆"""
        conn = await self._get_connection()
        cursor = await conn.execute(
            "SELECT * FROM permanent_memories WHERE id = ?", (memory_id,)
        )
        row = await cursor.fetchone()
        if row:
            return dict(row)
        return None

    async def get_permanent_memories(
        self, limit: int = 50, offset: int = 0
    ) -> List[Dict]:
        """获取永久记忆列表"""
        conn = await self._get_connection()
        cursor = await conn.execute(
            "SELECT * FROM permanent_memories ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_permanent_memory(
        self,
        memory_id: int,
        content: str = None,
        tags: List[str] = None,
        metadata: Dict = None,
        emotion_score: float = None,
        verified: bool = None,
    ) -> bool:
        """更新永久记忆"""
        conn = await self._get_connection()
        
        updates = []
        params = []
        
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if tags is not None:
            updates.append("tags = ?")
            params.append(json_dumps(tags))
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json_dumps(metadata))
        if emotion_score is not None:
            updates.append("emotion_score = ?")
            params.append(emotion_score)
        if verified is not None:
            updates.append("verified = ?")
            params.append(1 if verified else 0)
            
        if not updates:
            return False
            
        params.append(memory_id)
        cursor = await conn.execute(
            f"UPDATE permanent_memories SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def delete_permanent_memory(
        self, memory_id: int, is_from_main: bool = True
    ) -> bool:
        """删除永久记忆"""
        conn = await self._get_connection()
        cursor = await conn.execute(
            "DELETE FROM permanent_memories WHERE id = ?", (memory_id,)
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def sync_decay_values(self, workspace_id: str = "default") -> Dict:
        """同步衰减数值"""
        conn = await self._get_connection()
        
        cursor = await conn.execute(
            """
            UPDATE memories 
            SET decay_score = importance * (
                1.0 - (julianday('now') - julianday(created_at)) / 30.0
            )
            WHERE workspace_id = ? AND is_deleted = 0 AND permanent = 0
            """,
            (workspace_id,),
        )
        await conn.commit()
        
        return {"updated": cursor.rowcount}

    async def get_decay_statistics(self, workspace_id: str = "default") -> Dict:
        """获取衰减统计"""
        conn = await self._get_connection()
        
        cursor = await conn.execute(
            """
            SELECT 
                COUNT(*) as total,
                AVG(decay_score) as avg_decay,
                MIN(decay_score) as min_decay,
                MAX(decay_score) as max_decay
            FROM memories 
            WHERE workspace_id = ? AND is_deleted = 0 AND permanent = 0
            """,
            (workspace_id,),
        )
        row = await cursor.fetchone()
        
        return {
            "total": row["total"] or 0,
            "avg_decay": row["avg_decay"] or 0.0,
            "min_decay": row["min_decay"] or 0.0,
            "max_decay": row["max_decay"] or 0.0,
        }

    async def close(self):
        """关闭连接池"""
        async with self._pool_lock:
            if self._pool:
                await self._pool.close()
                self._pool = None
                self._initialized = False
                logger.info("AsyncMemoryManager 连接池已关闭")


async def get_async_memory_manager(db_path: str = "data/memories.db") -> AsyncMemoryManager:
    """获取异步记忆管理器单例"""
    manager = AsyncMemoryManager(db_path=db_path)
    await manager.initialize()
    return manager
