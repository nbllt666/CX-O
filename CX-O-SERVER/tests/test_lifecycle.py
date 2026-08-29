"""
server/core/lifecycle.py 回归测试
统一的服务初始化/关闭辅助函数（同步/异步分发、异常降级）
+ main.lifespan 会话清理接线回归（start 创建任务 / stop 取消 / run_once 清理）
"""
import logging

import pytest

from server.core.lifecycle import init_service, shutdown_service


async def _async_ok(a: int = 0, b: int = 0) -> int:
    return a + b


async def _async_fail():
    raise RuntimeError("async boom")


def _sync_ok(a: int = 0) -> int:
    return a + 1


def _sync_fail():
    raise ValueError("sync boom")


@pytest.mark.asyncio
class TestInitService:
    async def test_sync_factory(self, caplog):
        caplog.set_level(logging.INFO)
        result = await init_service("测试", _sync_ok, args=(5,))
        assert result == 6
        assert any("已启动" in r.message for r in caplog.records)

    async def test_async_factory(self):
        result = await init_service("测试", _async_ok, args=(2, 3))
        assert result == 5

    async def test_sync_factory_kwargs(self):
        result = await init_service("测试", _sync_ok, kwargs={"a": 10})
        assert result == 11

    async def test_sync_failure_returns_none(self, caplog):
        result = await init_service("测试", _sync_fail)
        assert result is None
        assert any("启动失败" in r.message for r in caplog.records)

    async def test_async_failure_returns_none(self):
        result = await init_service("测试", _async_fail)
        assert result is None


@pytest.mark.asyncio
class TestShutdownService:
    async def test_sync_close(self, caplog):
        caplog.set_level(logging.INFO)
        calls = []

        def _close():
            calls.append(1)

        await shutdown_service("测试", _close)
        assert calls == [1]
        assert any("已关闭" in r.message for r in caplog.records)

    async def test_async_close(self):
        calls = []

        async def _close():
            calls.append(1)

        await shutdown_service("测试", _close)
        assert calls == [1]

    async def test_sync_failure_caught(self, caplog):
        await shutdown_service("测试", _sync_fail)
        assert any("关闭失败" in r.message for r in caplog.records)

    async def test_async_failure_caught(self):
        await shutdown_service("测试", _async_fail)  # 不抛异常，仅告警


# --------------------------------------------------------------------------- #
# main.lifespan 会话清理接线回归
# 背景：start_session_cleanup 此前全仓无调用点，tuner_sessions.db 过期会话
# 永不清理。main.lifespan 全量装配过重（真实 DB/模型），故对新增接线的核心
# 语义做单元级验证：start 创建后台任务、stop 取消且不报错、run_once 真清理。
# DB 经 TUNER_SESSION_DB 重定向到 tmp，防真实落盘；单例状态保存/恢复。
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
class TestSessionCleanupWiring:
    @pytest.fixture
    def fresh_store(self, monkeypatch, tmp_path):
        import server.core.session.store as store_mod
        from server.core.session.store import get_session_store

        monkeypatch.setenv("TUNER_SESSION_DB", str(tmp_path / "tuner.db"))
        old = store_mod._session_store
        store_mod._session_store = None
        yield get_session_store()
        store_mod._session_store = old

    async def test_start_creates_background_task(self, fresh_store):
        import server.core.session.cleanup as cleanup_mod

        old_task = cleanup_mod._cleanup_task
        cleanup_mod._cleanup_task = None
        try:
            await cleanup_mod.start_session_cleanup(fresh_store)
            inst = cleanup_mod._cleanup_task
            assert inst is not None
            assert inst._task is not None
            assert not inst._task.done()
        finally:
            await cleanup_mod.stop_session_cleanup()
            cleanup_mod._cleanup_task = old_task

    async def test_stop_cancels_task_without_error(self, fresh_store):
        import server.core.session.cleanup as cleanup_mod

        old_task = cleanup_mod._cleanup_task
        cleanup_mod._cleanup_task = None
        try:
            await cleanup_mod.start_session_cleanup(fresh_store)
            inst = cleanup_mod._cleanup_task
            await cleanup_mod.stop_session_cleanup()
            # 任务已取消且被消费（CancelledError 不逸出），全局实例已复位
            assert inst._task is None
            assert cleanup_mod._cleanup_task is None
        finally:
            await cleanup_mod.stop_session_cleanup()
            cleanup_mod._cleanup_task = old_task

    async def test_run_once_cleans_expired_sessions(self, fresh_store):
        from server.core.session.cleanup import SessionCleanupTask

        expired = fresh_store.create_session(expires_in_days=-1)
        kept = fresh_store.create_session()
        task = SessionCleanupTask(fresh_store, max_session_age_days=30)
        await task.run_once()
        assert fresh_store.get_session(expired.id) is None
        assert fresh_store.get_session(kept.id) is not None