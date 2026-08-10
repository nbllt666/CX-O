"""提醒管理器（server.core.alarm.manager）回归保护测试。

使用独立临时目录数据库隔离；触发相关用例通过短延迟 + 轮询等待真实走通
threading.Timer 路径，避免 mock 掩盖调度逻辑。不可控的定时路径（超长延迟）
用极短秒数验证调度注册与取消。
"""
import threading
import time

import pytest

from server.core.alarm.manager import (
    MAX_DELAY,
    MAX_MESSAGE_LENGTH,
    Alarm,
    AlarmManager,
    get_alarm_manager,
    logger,
    reset_alarm_manager,
)


@pytest.fixture
def mgr(tmp_path):
    m = AlarmManager(db_path=str(tmp_path / "alarms.db"))
    yield m
    m.shutdown()  # 取消所有定时器并关闭连接，避免后台线程在测试结束后写已关闭的流


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
class TestAlarmModel:
    def test_to_dict_pending(self):
        import datetime

        now = datetime.datetime(2026, 8, 8, 12, 0, 0)
        a = Alarm(
            id="a1",
            agent_id="ag",
            message="msg",
            trigger_time=now,
            created_at=now,
            status="pending",
        )
        d = a.to_dict()
        assert d["id"] == "a1"
        assert d["status"] == "pending"
        assert d["trigger_time"] == "2026-08-08T12:00:00"
        assert "triggered_at" not in d

    def test_to_dict_triggered_includes_triggered_at(self):
        import datetime

        now = datetime.datetime(2026, 8, 8, 12, 0, 0)
        a = Alarm(
            id="a1",
            agent_id="ag",
            message="msg",
            trigger_time=now,
            created_at=now,
            status="triggered",
            triggered_at=now,
        )
        d = a.to_dict()
        assert d["triggered_at"] == "2026-08-08T12:00:00"


# --------------------------------------------------------------------------- #
# 连接与建表
# --------------------------------------------------------------------------- #
class TestInitialization:
    def test_db_created(self, tmp_path):
        db = tmp_path / "alarms.db"
        m = AlarmManager(db_path=str(db))
        assert db.exists()
        m.shutdown()

    def test_thread_connection_cache_and_close(self, mgr):
        c1 = mgr._get_connection()
        c2 = mgr._get_connection()
        assert c1 is c2  # 同线程复用
        mgr._close_all_connections()
        assert mgr._connection_cache == {}

    def test_cached_connection_recreated_after_close(self, mgr):
        c1 = mgr._get_connection()
        mgr._close_all_connections()
        c2 = mgr._get_connection()
        assert c2 is not c1
        assert mgr._connection_cache


# --------------------------------------------------------------------------- #
# 创建校验
# --------------------------------------------------------------------------- #
class TestCreateValidation:
    def test_invalid_agent_id(self, mgr):
        with pytest.raises(ValueError):
            mgr.create_alarm("", 10, "x")
        with pytest.raises(ValueError):
            mgr.create_alarm("   ", 10, "x")

    def test_invalid_seconds(self, mgr):
        with pytest.raises(ValueError):
            mgr.create_alarm("ag", 0, "x")
        with pytest.raises(ValueError):
            mgr.create_alarm("ag", -1, "x")
        with pytest.raises(ValueError):
            mgr.create_alarm("ag", MAX_DELAY + 1, "x")

    def test_invalid_message(self, mgr):
        with pytest.raises(ValueError):
            mgr.create_alarm("ag", 10, "x" * (MAX_MESSAGE_LENGTH + 1))

    def test_create_and_get(self, mgr):
        aid = mgr.create_alarm("ag", 600, "喝水")
        alarm = mgr.get_alarm(aid)
        assert alarm is not None
        assert alarm["agent_id"] == "ag"
        assert alarm["message"] == "喝水"
        assert alarm["status"] == "pending"

    def test_get_missing(self, mgr):
        assert mgr.get_alarm("nope") is None


# --------------------------------------------------------------------------- #
# 查询
# --------------------------------------------------------------------------- #
class TestQuery:
    def _seed(self, mgr):
        ids = [mgr.create_alarm("ag", 100, f"m{i}") for i in range(3)]
        mgr.create_alarm("other", 100, "other")
        return ids

    def test_by_agent_pending_only(self, mgr):
        self._seed(mgr)
        rows = mgr.get_alarms_by_agent("ag")
        assert len(rows) == 3
        assert all(r["status"] == "pending" for r in rows)
        assert all(r["agent_id"] == "ag" for r in rows)

    def test_by_agent_include_triggered(self, mgr):
        ids = self._seed(mgr)
        mgr.mark_triggered(ids[0])
        rows = mgr.get_alarms_by_agent("ag", include_triggered=True)
        assert len(rows) == 3
        rows_pending = mgr.get_alarms_by_agent("ag")
        assert len(rows_pending) == 2

    def test_pending_alarms(self, mgr):
        self._seed(mgr)
        rows = mgr.get_pending_alarms()
        assert len(rows) == 4


# --------------------------------------------------------------------------- #
# 生命周期：取消 / 触发
# --------------------------------------------------------------------------- #
class TestLifecycle:
    def test_cancel_alarm(self, mgr):
        aid = mgr.create_alarm("ag", 600, "x")
        assert mgr.cancel_alarm(aid) is True
        assert mgr.get_alarm(aid)["status"] == "cancelled"
        # 再次取消已取消的 → False
        assert mgr.cancel_alarm(aid) is False

    def test_cancel_missing(self, mgr):
        assert mgr.cancel_alarm("nope") is False

    def test_mark_triggered(self, mgr):
        aid = mgr.create_alarm("ag", 600, "x")
        assert mgr.mark_triggered(aid) is True
        row = mgr.get_alarm(aid)
        assert row["status"] == "triggered"
        assert row["triggered_at"] is not None
        # 二次标记仍返回 True（UPDATE 不校验 status）
        assert mgr.mark_triggered(aid) is True


# --------------------------------------------------------------------------- #
# 定时触发（短延迟真实路径）
# --------------------------------------------------------------------------- #
class TestTriggerSchedule:
    def test_alarm_fires_callback(self, mgr):
        fired = []

        def cb(agent_id, message):
            fired.append((agent_id, message))

        mgr.set_trigger_callback(cb)
        aid = mgr.create_alarm("ag", 0.05, "提醒")
        # 轮询等待触发
        deadline = time.time() + 3
        while time.time() < deadline and not fired:
            time.sleep(0.02)
        assert fired == [("ag", "提醒")]
        assert mgr.get_alarm(aid)["status"] == "triggered"
        mgr.shutdown()

    def test_callback_exception_is_swallowed(self, mgr):
        def bad_cb(a, m):
            raise RuntimeError("boom")

        mgr.set_trigger_callback(bad_cb)
        mgr.create_alarm("ag", 0.05, "x")
        time.sleep(0.2)
        mgr.shutdown()  # 不应抛异常


# --------------------------------------------------------------------------- #
# 恢复 / 关闭
# --------------------------------------------------------------------------- #
class TestRestoreShutdown:
    def test_restore_pending_alarms_past(self, mgr):
        # 已过期的 pending 在恢复时立即触发
        aid = mgr.create_alarm("ag", 600, "x")
        # 把触发时间改到过去
        import datetime

        conn = mgr._get_connection()
        past = (datetime.datetime.now() - datetime.timedelta(seconds=10)).isoformat()
        conn.execute("UPDATE alarms SET trigger_time = ? WHERE id = ?", (past, aid))
        conn.commit()
        mgr.restore_pending_alarms()
        assert mgr.get_alarm(aid)["status"] == "triggered"
        mgr.shutdown()

    def test_restore_schedules_future(self, mgr):
        aid = mgr.create_alarm("ag", 600, "x")
        mgr.restore_pending_alarms()
        assert aid in mgr._timers
        mgr.shutdown()

    def test_shutdown_cancels_timers_and_closes(self, mgr):
        aid = mgr.create_alarm("ag", 600, "x")
        mgr.shutdown()
        assert aid not in mgr._timers
        assert mgr._shutdown is True
        assert mgr._connection_cache == {}

    def test_trigger_skipped_after_shutdown(self, mgr):
        mgr.shutdown()
        mgr._trigger_alarm(Alarm("a", "ag", "m", None, None))

    def test_silence_logger(self, mgr):
        import logging

        from server.core.alarm.manager import _silence_logger

        _silence_logger()
        assert all(isinstance(h, logging.NullHandler) for h in logger.handlers)
        mgr.shutdown()


# --------------------------------------------------------------------------- #
# 异步包装
# --------------------------------------------------------------------------- #
class TestAsync:
    def test_async_wrappers(self, mgr):
        import asyncio

        async def run():
            aid = await mgr.acreate_alarm("ag", 600, "x")
            assert await mgr.aget_alarm(aid) is not None
            assert len(await mgr.aget_alarms_by_agent("ag")) == 1
            assert len(await mgr.aget_pending_alarms()) == 1
            assert await mgr.acancel_alarm(aid) is True
            assert await mgr.acancel_alarm(aid) is False
            await mgr.arestore_pending_alarms()
            aid2 = await mgr.acreate_alarm("ag", 600, "y")
            assert await mgr.amark_triggered(aid2) is True

        asyncio.run(run())
        mgr.shutdown()


# --------------------------------------------------------------------------- #
# 单例
# --------------------------------------------------------------------------- #
class TestSingleton:
    def test_get_reset(self):
        reset_alarm_manager()
        m1 = get_alarm_manager()
        m2 = get_alarm_manager()
        assert m1 is m2
        reset_alarm_manager()
        m3 = get_alarm_manager()
        assert m3 is not m1
        m3.shutdown()