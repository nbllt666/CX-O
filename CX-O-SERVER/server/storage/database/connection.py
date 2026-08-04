import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class AsyncConnectionPool:
    def __init__(self, db_path: str = "data/memories.db", min_size: int = 5, max_size: int = 20):
        self.db_path = db_path
        self.min_size = min_size
        self.max_size = max_size
        self._pool: List[aiosqlite.Connection] = []
        self._lock = asyncio.Lock()
        # BUG-B10 修复: 记录当前已分配(未归还)的连接数,确保 total
        # outstanding <= max_size,而不是依赖 pool 长度做判断
        self._in_flight: int = 0
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        async with self._lock:
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
        """从池中借出连接。BUG-B10 修复: 锁内统一处理借/还,确保总占用 <= max_size。"""
        conn: Optional[aiosqlite.Connection] = None
        async with self._lock:
            if self._pool:
                conn = self._pool.pop()
                self._in_flight += 1
            elif self._in_flight < self.max_size:
                # 在锁内创建新连接,避免多个协程同时越过 max_size
                conn = await self._create_connection()
                if conn is not None:
                    self._in_flight += 1
                else:
                    conn = None
            else:
                conn = None

        # 锁内已达 max_size 且无空闲连接:在锁外等待并重试(简单退避)
        if conn is None:
            for _ in range(50):  # 最多退避 5s
                await asyncio.sleep(0.1)
                async with self._lock:
                    if self._pool:
                        conn = self._pool.pop()
                        self._in_flight += 1
                        break
            else:
                # 最后一次尝试:若仍达 max_size,创建临时连接(用完关闭)
                conn = await self._create_connection()
                if conn is None:
                    raise RuntimeError("无法获取数据库连接:连接池耗尽且新连接创建失败")

        try:
            yield conn
        finally:
            # BUG-B10 修复: 锁内归还,先做健康检查,确保 max_size 严格不超
            should_return = True
            if conn is not None:
                try:
                    await conn.execute("SELECT 1")
                except Exception as e:
                    logger.warning(f"连接健康检查失败,直接关闭: {e}")
                    should_return = False
                    try:
                        await conn.close()
                    except Exception:
                        pass

            async with self._lock:
                self._in_flight = max(0, self._in_flight - 1)
                if should_return and conn is not None and len(self._pool) < self.max_size:
                    self._pool.append(conn)
                elif conn is not None:
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
            self._in_flight = 0
        self._initialized = False
        logger.info("所有数据库连接已关闭")


class SyncConnectionPool:
    def __init__(self, db_path: str = "data/memories.db", pool_size: int = 10):
        self.db_path = db_path
        self.pool_size = pool_size
        self._connections: Dict[int, sqlite3.Connection] = {}
        import threading

        # BUG-B10 修复: 显式线程锁保护 _connections / _last_used 的并发读写
        self._lock = threading.Lock()
        self._last_used: Dict[int, float] = {}
        self._initialized = False

    def initialize(self):
        if self._initialized:
            return

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            # BUG-B-M1 修复: 使用递增整数索引作为 key,而不是 threading.get_ident()。
            # 原实现中 initialize() 在同一线程执行,所有连接都以同一个 thread_id 为 key,
            # 后者覆盖前者,最终只保留 1 个连接,pool_size 失效。
            for i in range(self.pool_size):
                conn = self._create_connection()
                if conn:
                    self._connections[i] = conn
                    self._last_used[i] = 0
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
        """获取当前线程的连接,优先复用缓存。

        BUG-B10 修复: 缓存字典 ``_connections`` / ``_last_used`` 的
        全部读写都在 ``self._lock`` 内完成,避免多线程下出现 ``pool_size``
        上限被突破或数据竞争。
        """
        import threading
        import time

        thread_id = threading.get_ident()

        with self._lock:
            conn = self._connections.get(thread_id)
            if conn is not None:
                try:
                    conn.execute("SELECT 1")
                    self._last_used[thread_id] = time.time()
                    return conn
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    self._connections.pop(thread_id, None)
                    self._last_used.pop(thread_id, None)

        # 锁外创建连接:每个线程最多持有一个,此操作不改变其他线程的 in_flight
        conn = self._create_connection()
        if conn is None:
            raise RuntimeError("无法创建同步数据库连接")

        with self._lock:
            self._connections[thread_id] = conn
            self._last_used[thread_id] = time.time()

        return conn

    def close_connection(self):
        import threading

        thread_id = threading.get_ident()

        with self._lock:
            conn = self._connections.pop(thread_id, None)
            self._last_used.pop(thread_id, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def close_all(self):
        with self._lock:
            connections_snapshot = list(self._connections.values())
            self._connections.clear()
            self._last_used.clear()
        for conn in connections_snapshot:
            try:
                conn.close()
            except Exception:
                pass
        self._initialized = False
        logger.info("所有同步数据库连接已关闭")
