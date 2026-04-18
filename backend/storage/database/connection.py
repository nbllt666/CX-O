import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class AsyncConnectionPool:
    def __init__(self, db_path: str = "data/memories.db", min_size: int = 5, max_size: int = 20):
        self.db_path = db_path
        self.min_size = min_size
        self.max_size = max_size
        self._pool: List[aiosqlite.Connection] = []
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        for _ in range(self.min_size):
            conn = await self._create_connection()
            if conn:
                self._pool.append(conn)

        self._initialized = True
        logger.info(f"连接池初始化完成: {len(self._pool)} 个连接")

    async def _create_connection(self) -> Optional[aiosqlite.Connection]:
        try:
            conn = await aiosqlite.connect(self.db_path, timeout=20.0)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=-64000")
            await conn.execute("PRAGMA temp_store=MEMORY")
            return conn
        except Exception as e:
            logger.error(f"创建数据库连接失败: {e}")
            return None

    @asynccontextmanager
    async def get_connection(self):
        async with self._lock:
            if self._pool:
                conn = self._pool.pop()
            else:
                if len(self._pool) < self.max_size:
                    conn = await self._create_connection()
                else:
                    conn = None

        if conn is None:
            conn = await self._create_connection()

        try:
            yield conn
        finally:
            if conn:
                try:
                    await conn.execute("SELECT 1")
                    async with self._lock:
                        if len(self._pool) < self.max_size:
                            self._pool.append(conn)
                        else:
                            await conn.close()
                except Exception as e:
                    logger.warning(f"连接回收失败: {e}")
                    try:
                        await conn.close()
                    except Exception:
                        pass

    async def close_all(self):
        async with self._lock:
            for conn in self._pool:
                try:
                    await conn.close()
                except Exception as e:
                    logger.warning(f"关闭连接失败: {e}")
            self._pool.clear()
        self._initialized = False
        logger.info("所有数据库连接已关闭")


class SyncConnectionPool:
    def __init__(self, db_path: str = "data/memories.db", pool_size: int = 10):
        self.db_path = db_path
        self.pool_size = pool_size
        self._connections: Dict[int, sqlite3.Connection] = {}
        import threading

        self._lock = threading.Lock()
        self._last_used: Dict[int, float] = {}
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        for _ in range(self.pool_size):
            conn = self._create_connection()
            if conn:
                import threading

                thread_id = threading.get_ident()
                self._connections[thread_id] = conn
                self._last_used[thread_id] = 0

        self._initialized = True
        logger.info(f"同步连接池初始化完成: {len(self._connections)} 个连接")

    def _create_connection(self) -> Optional[sqlite3.Connection]:
        try:
            conn = sqlite3.connect(self.db_path, timeout=20.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-64000")
            conn.execute("PRAGMA temp_store=MEMORY")
            return conn
        except Exception as e:
            logger.error(f"创建同步数据库连接失败: {e}")
            return None

    def get_connection(self) -> sqlite3.Connection:
        import threading
        import time

        thread_id = threading.get_ident()

        if thread_id in self._connections:
            conn = self._connections[thread_id]
            try:
                conn.execute("SELECT 1")
                self._last_used[thread_id] = time.time()
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                del self._connections[thread_id]
                del self._last_used[thread_id]

        conn = self._create_connection()
        if conn:
            self._connections[thread_id] = conn
            self._last_used[thread_id] = time.time()

        return conn

    def close_connection(self):
        import threading

        thread_id = threading.get_ident()

        if thread_id in self._connections:
            try:
                self._connections[thread_id].close()
            except Exception:
                pass
            del self._connections[thread_id]
            del self._last_used[thread_id]

    def close_all(self):
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()
        self._last_used.clear()
        self._initialized = False
        logger.info("所有同步数据库连接已关闭")
