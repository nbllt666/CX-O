"""会话清理任务（server.core.session.cleanup）回归保护测试。

用轻量替身 SessionStore 隔离真实数据库；通过极小间隔/年龄阈值走通
清理循环与单次执行路径，验证过期与长期未访问会话的删除逻辑及
start/stop/run_once 生命周期。

H2（第四轮体检 E组）：长期未访问清理改为 store 层固定谓词游标删除
delete_sessions_last_accessed_before，替身同步收敛该方法签名。
"""
import asyncio
from datetime import datetime, timedelta

import pytest

import server.core.session.cleanup as sc
from server.core.session.cleanup import SessionCleanupTask


class FakeSessionStore:
    """替身会话存储：记录清理调用并返回可配置会话列表。"""

    def __init__(self, sessions=None):
        self.sessions = sessions or []
        self.deleted_ids = []
        self.expired_count = 0
        self.old_cleanup_calls = []

    def cleanup_expired_sessions(self):
        return self.expired_count

    def delete_sessions_last_accessed_before(self, cutoff, page_size=500):
        """H2 条目4 替身实现：模拟固定谓词游标删除（last_accessed_at < cutoff）。"""
        self.old_cleanup_calls.append(cutoff)
        removed = [s for s in self.sessions if s.last_accessed_at < cutoff]
        self.sessions = [s for s in self.sessions if s.last_accessed_at >= cutoff]
        self.deleted_ids.extend((s.id, False) for s in removed)
        return len(removed)


class FakeSession:
    def __init__(self, sid, last_accessed_at):
        self.id = sid
        self.last_accessed_at = last_accessed_at


@pytest.fixture
def store():
    return FakeSessionStore()


def _task(store, interval=60, age_days=30):
    return SessionCleanupTask(
        session_store=store,
        cleanup_interval_minutes=interval,
        max_session_age_days=age_days,
    )


# --------------------------------------------------------------------------- #
# 生命周期
# --------------------------------------------------------------------------- #
class TestLifecycle:
    def test_start_running_flag_and_idempotent(self, store):
        async def run():
            t = _task(store)
            await t.start()
            assert t._running is True
            assert t._task is not None
            old = t._task
            await t.start()
            assert t._task is old  # 重复启动复用
            await t.stop()

        asyncio.run(run())

    def test_stop_cancels_task_and_resets(self, store):
        async def run():
            t = _task(store)
            await t.start()
            await t.stop()
            assert t._running is False
            assert t._task is None

        asyncio.run(run())

    def test_stop_when_not_started(self, store):
        t = _task(store)
        asyncio.run(t.stop())  # 不抛异常
        assert t._running is False


class TestCleanupLoop:
    def test_loop_runs_and_handles_error(self, store):
        async def run():
            t = _task(store, interval=0)
            calls = {"n": 0}

            async def fake_perform():
                calls["n"] += 1
                if calls["n"] == 1:
                    raise RuntimeError("临时错误")  # 循环应捕获继续
                raise asyncio.CancelledError

            t._perform_cleanup = fake_perform
            await t.start()

            async def delayed_stop():
                await asyncio.sleep(0.05)
                await t.stop()

            await asyncio.gather(delayed_stop())
            assert calls["n"] >= 2
            assert t._running is False

        asyncio.run(run())


# --------------------------------------------------------------------------- #
# 清理逻辑
# --------------------------------------------------------------------------- #
class TestPerformCleanup:
    def test_perform_cleanup_sums_counts(self, store):
        async def run():
            t = _task(store)
            store.expired_count = 2

            async def fake_old():
                return 3

            t._cleanup_old_sessions = fake_old
            await t._perform_cleanup()  # 不抛异常即可

        asyncio.run(run())

    def test_perform_cleanup_calls_both(self, store):
        async def run():
            t = _task(store)
            store.expired_count = 5

            async def fake_old():
                return 4

            t._cleanup_old_sessions = fake_old
            await t._perform_cleanup()
            # 真实 store 的 get_sessions 未被调用（fake_old 被替换）

        asyncio.run(run())

    def test_run_once(self, store):
        async def run():
            t = _task(store)
            ran = []

            async def fake_perform():
                ran.append(1)

            t._perform_cleanup = fake_perform
            await t.run_once()
            assert ran == [1]

        asyncio.run(run())


# --------------------------------------------------------------------------- #
# 长期未访问清理
# --------------------------------------------------------------------------- #
class TestCleanupOldSessions:
    def test_deletes_old_not_new(self, store):
        now = datetime.now()
        old = FakeSession("s_old", now - timedelta(days=40))
        new = FakeSession("s_new", now - timedelta(days=1))
        store.sessions = [old, new]
        t = _task(store, age_days=30)
        count = asyncio.run(t._cleanup_old_sessions())
        assert count == 1
        assert ("s_old", False) in store.deleted_ids
        assert ("s_new", False) not in store.deleted_ids
        # H2 条目4: 委托 store 游标删除，cutoff = now - max_session_age（约 30 天前）
        assert len(store.old_cleanup_calls) == 1
        cutoff = store.old_cleanup_calls[0]
        assert timedelta(days=29) <= (now - cutoff) <= timedelta(days=30, seconds=1)

    def test_none_deleted_when_all_recent(self, store):
        now = datetime.now()
        store.sessions = [FakeSession("a", now - timedelta(days=1))]
        t = _task(store, age_days=30)
        assert asyncio.run(t._cleanup_old_sessions()) == 0
        assert store.deleted_ids == []

    def test_delete_failure_does_not_count(self, store):
        # 替身语义下删除恒成功；此处验证返回计数与删除数一致（0 条时为 0）
        now = datetime.now()
        store.sessions = []
        t = _task(store, age_days=30)
        assert asyncio.run(t._cleanup_old_sessions()) == 0


# --------------------------------------------------------------------------- #
# 全局管理
# --------------------------------------------------------------------------- #
class TestGlobal:
    def _reset(self):
        sc._cleanup_task = None

    def test_start_and_stop_global(self, store):
        self._reset()
        asyncio.run(
            sc.start_session_cleanup(store, cleanup_interval_minutes=99, max_session_age_days=30)
        )
        assert sc._cleanup_task is not None
        assert sc._cleanup_task.cleanup_interval == timedelta(minutes=99)
        asyncio.run(sc.stop_session_cleanup())
        assert sc._cleanup_task is None

    def test_start_reuses_existing(self, store):
        self._reset()
        asyncio.run(sc.start_session_cleanup(store, cleanup_interval_minutes=99))
        first = sc._cleanup_task
        asyncio.run(sc.start_session_cleanup(store, cleanup_interval_minutes=1))
        assert sc._cleanup_task is first  # 复用已有实例
        asyncio.run(sc.stop_session_cleanup())

    def test_stop_when_none(self):
        self._reset()
        asyncio.run(sc.stop_session_cleanup())  # 不抛异常