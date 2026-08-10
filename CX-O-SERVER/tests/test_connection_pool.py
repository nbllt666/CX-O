"""server.storage.database.connection（Async/Sync 连接池）单元测试。

使用 tmp_path 隔离真实 SQLite 文件，聚焦连接池的并发不变量：

AsyncConnectionPool:
- initialize 建 min_size 连接、幂等
- get_connection 借出/健康检查/归还，in_flight 严格追踪
- 池空且未达 max_size 时锁内新建
- 已达 max_size 时退避重试 → 临时连接兜底（monkeypatch asyncio.sleep 提速）
- close_all 清池

SyncConnectionPool:
- initialize 建 pool_size 连接
- get_connection 按线程缓存复用 / 失效重建
- close_connection / close_all

运行：python -m pytest tests/test_connection_pool.py -v
"""
import asyncio

import pytest

from server.storage.database.connection import AsyncConnectionPool, SyncConnectionPool


async def _no_sleep(*args, **kwargs):
    return


_async_pools = []


def _new_async_pool(*args, **kwargs):
    p = AsyncConnectionPool(*args, **kwargs)
    _async_pools.append(p)
    return p


async def _close_async_pools():
    """关闭本用例创建的 aiosqlite 连接，避免 worker 线程在 loop 关闭后仍运行。"""
    while _async_pools:
        p = _async_pools.pop()
        try:
            await p.close_all()
        except Exception:
            pass


# ================================================================ AsyncConnectionPool
class TestAsyncPool:
    @pytest.mark.asyncio
    async def test_initialize_creates_min(self, tmp_path):
        p = _new_async_pool(str(tmp_path / "m.db"), min_size=3, max_size=10)
        await p.initialize()
        assert p._initialized is True
        assert len(p._pool) == 3
        await _close_async_pools()

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, tmp_path):
        p = _new_async_pool(str(tmp_path / "m.db"), min_size=2, max_size=10)
        await p.initialize()
        await p.initialize()
        assert len(p._pool) == 2
        await _close_async_pools()

    @pytest.mark.asyncio
    async def test_borrow_return_health_checked(self, tmp_path):
        p = _new_async_pool(str(tmp_path / "m.db"), min_size=2, max_size=10)
        await p.initialize()
        before = len(p._pool)
        async with p.get_connection() as conn:
            assert conn is not None
            cur = await conn.execute("SELECT 1")
            row = await cur.fetchone()
            assert row[0] == 1
            # 借出后池少一个、in_flight +1
            assert len(p._pool) == before - 1
            assert p._in_flight == 1
        # 归还后池恢复、in_flight 归零
        assert len(p._pool) == before
        assert p._in_flight == 0
        await _close_async_pools()

    @pytest.mark.asyncio
    async def test_borrow_creates_new_when_below_max(self, tmp_path):
        p = _new_async_pool(str(tmp_path / "m.db"), min_size=0, max_size=10)
        await p.initialize()
        async with p.get_connection() as conn:
            assert conn is not None
            # min=0 时池为空，在 max 内锁内新建
            assert p._in_flight == 1
        await _close_async_pools()

    @pytest.mark.asyncio
    async def test_at_max_backoff_then_temp_fallback(self, tmp_path, monkeypatch):
        p = _new_async_pool(str(tmp_path / "m.db"), min_size=0, max_size=1)
        await p.initialize()
        monkeypatch.setattr(asyncio, "sleep", _no_sleep)
        async with p.get_connection() as c1:
            assert c1 is not None
            # 池空且 in_flight==max_size(1) → 退避 50 次未得 → 临时连接兜底
            async with p.get_connection() as c2:
                assert c2 is not None
        await _close_async_pools()

    @pytest.mark.asyncio
    async def test_health_check_failure_closes_not_returns(self, tmp_path, monkeypatch):
        p = _new_async_pool(str(tmp_path / "m.db"), min_size=1, max_size=5)
        await p.initialize()

        async def broken_execute(sql):
            raise RuntimeError("connection dead")

        monkeypatch.setattr(p._pool[0], "execute", broken_execute)
        before = len(p._pool)
        async with p.get_connection() as conn:
            assert conn is not None
        # 健康检查失败 → 不归还，连接被关闭
        assert len(p._pool) == before - 1
        assert p._in_flight == 0
        await _close_async_pools()

    @pytest.mark.asyncio
    async def test_close_all_clears(self, tmp_path):
        p = _new_async_pool(str(tmp_path / "m.db"), min_size=2, max_size=10)
        await p.initialize()
        await p.close_all()
        assert p._pool == []
        assert p._in_flight == 0
        assert p._initialized is False
        await _close_async_pools()


# ================================================================ SyncConnectionPool
class TestSyncPool:
    def test_initialize_creates_pool_size(self, tmp_path):
        p = SyncConnectionPool(str(tmp_path / "m.db"), pool_size=4)
        p.initialize()
        assert p._initialized is True
        assert len(p._connections) == 4

    def test_get_connection_caches_per_thread(self, tmp_path):
        p = SyncConnectionPool(str(tmp_path / "m.db"), pool_size=4)
        p.initialize()
        c1 = p.get_connection()
        c2 = p.get_connection()
        # 同一线程 → 复用同一连接（按 threading.get_ident() 缓存）
        assert c1 is c2
        # 注：initialize 以整数索引 0..pool_size-1 预建连接，而 get_connection 以
        # thread_id 为 key，故预建连接不会被复用，线程连接为按需新建（见变更文档记录）。
        assert len(p._connections) == 4 + 1

    def test_close_connection_removes(self, tmp_path):
        p = SyncConnectionPool(str(tmp_path / "m.db"), pool_size=2)
        p.initialize()
        p.get_connection()
        thread_key = list(p._connections)[-1]  # 线程连接以 thread_id 为 key
        p.close_connection()
        assert thread_key not in p._connections
        assert thread_key not in p._last_used

    def test_close_all_clears(self, tmp_path):
        p = SyncConnectionPool(str(tmp_path / "m.db"), pool_size=2)
        p.initialize()
        p.get_connection()
        p.close_all()
        assert p._connections == {}
        assert p._initialized is False
