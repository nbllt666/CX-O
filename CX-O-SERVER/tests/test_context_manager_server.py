"""server.core.context.manager (ContextManager) 单元测试。

覆盖会话/消息 CRUD、软删除、统计、Mono 上下文等核心逻辑。
使用 pytest tmp_path 创建独立临时数据库，不污染真实数据。

运行：python -m pytest tests/test_context_manager_server.py -v
"""
import pytest

from server.core.context.manager import ContextManager


@pytest.fixture
def mgr(tmp_path):
    """每个用例独立的临时数据库 ContextManager。"""
    db_path = str(tmp_path / "sessions.db")
    m = ContextManager(db_path=db_path)
    yield m
    m.shutdown()


def _new_session(mgr, title="测试会话"):
    return mgr.create_session(title=title)


class TestSessionCRUD:
    def test_create_and_get_session(self, mgr):
        sid = _new_session(mgr)
        session = mgr.get_session(sid)
        assert session is not None
        assert session["id"] == sid
        assert session["title"] == "测试会话"

    def test_get_missing_session_returns_none(self, mgr):
        assert mgr.get_session("nonexistent") is None

    def test_get_sessions_returns_created(self, mgr):
        sid = _new_session(mgr)
        sessions = mgr.get_sessions()
        assert any(s["id"] == sid for s in sessions)

    def test_update_session_title(self, mgr):
        sid = _new_session(mgr, title="旧标题")
        assert mgr.update_session(sid, title="新标题") is True
        assert mgr.get_session(sid)["title"] == "新标题"

    def test_update_session_no_fields_returns_false(self, mgr):
        sid = _new_session(mgr)
        assert mgr.update_session(sid) is False

    def test_delete_session(self, mgr):
        sid = _new_session(mgr)
        mgr.add_message(sid, "user", "你好")
        assert mgr.delete_session(sid) is True
        assert mgr.get_session(sid) is None
        # 关联消息一并删除
        assert mgr.get_message_count(sid) == 0

    def test_clear_all_sessions(self, mgr):
        _new_session(mgr, title="A")
        _new_session(mgr, title="B")
        assert mgr.clear_all_sessions() == 2
        assert mgr.get_sessions() == []


class TestSessionEnsure:
    def test_ensure_session_creates(self, mgr):
        sid = mgr.ensure_session("s-new", workspace_id="agent-chats", title="新会话")
        assert sid == "s-new"
        session = mgr.get_session("s-new")
        assert session is not None
        assert session["title"] == "新会话"

    def test_ensure_session_existing_returns_same(self, mgr):
        sid = _new_session(mgr, title="已有")
        # 已存在时不应触发 create_session（标题不被覆盖）
        ret = mgr.ensure_session(sid, workspace_id="agent-chats", title="不应覆盖")
        assert ret == sid
        assert mgr.get_session(sid)["title"] == "已有"


class TestMessageCRUD:
    def test_add_and_get_message(self, mgr):
        sid = _new_session(mgr)
        mid = mgr.add_message(sid, "user", "你好")
        msgs = mgr.get_messages(sid)
        assert len(msgs) == 1
        assert msgs[0]["id"] == mid
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "你好"

    def test_invalid_role_raises(self, mgr):
        sid = _new_session(mgr)
        with pytest.raises(ValueError):
            mgr.add_message(sid, "invalid_role", "内容")

    def test_get_messages_returns_in_insertion_order(self, mgr):
        sid = _new_session(mgr)
        mgr.add_message(sid, "user", "m1")
        mgr.add_message(sid, "assistant", "m2")
        mgr.add_message(sid, "user", "m3")
        contents = [m["content"] for m in mgr.get_messages(sid)]
        assert contents == ["m1", "m2", "m3"]

    def test_get_messages_limit(self, mgr):
        sid = _new_session(mgr)
        for i in range(5):
            mgr.add_message(sid, "user", f"m{i}")
        msgs = mgr.get_messages(sid, limit=3)
        assert len(msgs) == 3
        assert [m["content"] for m in msgs] == ["m0", "m1", "m2"]

    def test_get_messages_offset(self, mgr):
        sid = _new_session(mgr)
        for i in range(5):
            mgr.add_message(sid, "user", f"m{i}")
        msgs = mgr.get_messages(sid, limit=5, offset=2)
        assert [m["content"] for m in msgs] == ["m2", "m3", "m4"]

    def test_get_recent_messages(self, mgr):
        """单次查询取最近 N 条，返回升序（与 get_messages 语义一致）。"""
        sid = _new_session(mgr)
        for i in range(5):
            mgr.add_message(sid, "user", f"m{i}")
        recent = mgr.get_recent_messages(sid, limit=3)
        # 最近 3 条且按旧→新：m2, m3, m4
        assert [m["content"] for m in recent] == ["m2", "m3", "m4"]
        # limit ≥ 全部时返回全部
        assert len(mgr.get_recent_messages(sid, limit=99)) == 5
        # 空会话返回空
        assert mgr.get_recent_messages(_new_session(mgr), limit=3) == []

    def test_get_message_count(self, mgr):
        sid = _new_session(mgr)
        assert mgr.get_message_count(sid) == 0
        mgr.add_message(sid, "user", "a")
        mgr.add_message(sid, "assistant", "b")
        assert mgr.get_message_count(sid) == 2

    def test_delete_message_soft_delete(self, mgr):
        sid = _new_session(mgr)
        mid = mgr.add_message(sid, "user", "你好")
        assert mgr.delete_message(mid) is True
        # 默认不包含已删除
        assert mgr.get_messages(sid) == []
        # 显式包含已删除
        assert len(mgr.get_messages(sid, include_deleted=True)) == 1
        # 计数不含已删除
        assert mgr.get_message_count(sid) == 0

    def test_clear_session_messages(self, mgr):
        sid = _new_session(mgr)
        mgr.add_message(sid, "user", "a")
        mgr.add_message(sid, "assistant", "b")
        assert mgr.clear_session_messages(sid) is True
        assert mgr.get_message_count(sid) == 0


class TestStats:
    def test_get_statistics_basic(self, mgr):
        sid = _new_session(mgr, title="A")
        mgr.add_message(sid, "user", "a")
        mgr.add_message(sid, "assistant", "b")
        stats = mgr.get_statistics()
        assert stats["total_sessions"] == 1
        assert stats["active_sessions"] == 1
        assert stats["total_messages"] == 2
        assert stats["avg_messages_per_session"] == 2.0

    def test_get_statistics_zero(self, mgr):
        stats = mgr.get_statistics()
        assert stats["total_sessions"] == 0
        assert stats["avg_messages_per_session"] == 0


class TestMonoContext:
    def test_add_and_get_mono_context(self, mgr):
        sid = _new_session(mgr)
        assert mgr.add_mono_context(sid, "保持信息", rounds=1) is True
        contexts = mgr.get_mono_context(sid)
        assert len(contexts) == 1
        assert contexts[0]["content"] == "保持信息"
        assert contexts[0]["content_type"] == "mono_context"

    def test_get_mono_context_on_missing_session(self, mgr):
        assert mgr.get_mono_context("nonexistent") == []


# --------------------------------------------------------------------------- #
# H2（第四轮体检 E组）追加验证
# --------------------------------------------------------------------------- #
class TestSoftDeleteDecrement:
    """H2 条目3: 软删消息同事务回减 message_count（下限 0）。"""

    def test_delete_message_decrements_session_count(self, mgr):
        sid = _new_session(mgr)
        m1 = mgr.add_message(sid, "user", "a")
        mgr.add_message(sid, "user", "b")
        assert mgr.get_session(sid)["message_count"] == 2

        assert mgr.delete_message(m1) is True
        # 会话持久化计数同步回减（而非仅查询侧过滤）
        assert mgr.get_session(sid)["message_count"] == 1

    def test_delete_missing_message_no_decrement(self, mgr):
        sid = _new_session(mgr)
        mgr.add_message(sid, "user", "a")
        before = mgr.get_session(sid)["message_count"]
        assert mgr.delete_message("no-such-id") is False
        assert mgr.get_session(sid)["message_count"] == before

    def test_clear_expired_mono_decrements_count(self, mgr):
        """clear_expired_mono 亦为 is_deleted=TRUE 软删入口，需回减计数。"""
        sid = _new_session(mgr)
        mgr.add_message(sid, "user", "普通消息")
        # rounds=-1 → expires_at 在过去 → 立即可清理
        assert mgr.add_mono_context(sid, "过期mono", rounds=-1) is True
        count_after_add = mgr.get_session(sid)["message_count"]
        assert count_after_add == 2

        deleted = mgr.clear_expired_mono()
        assert deleted >= 1
        got = mgr.get_session(sid)
        # 普通消息仍在；mono 软删已回减，剩余计数=普通消息数
        assert got["message_count"] == 1
        assert mgr.get_messages(sid)[0]["content"] == "普通消息"


class TestShutdownGeneration:
    """H2 条目2: shutdown 后其他线程陈旧连接按代际弃置重建，不再误用已关闭连接。"""

    def test_worker_thread_reconnects_after_shutdown(self, tmp_path):
        import threading

        m = ContextManager(db_path=str(tmp_path / "gen.db"))
        started = threading.Event()
        shutdown_done = threading.Event()
        worker_done = threading.Event()
        errors, results = [], []

        def worker():
            try:
                conn = m._get_connection()  # 该线程 thread-local：第 0 代连接
                assert conn is not None
                started.set()
                shutdown_done.wait(timeout=5)
                # shutdown 后再次取连接并执行完整读写——旧实现此处抛
                # "Cannot operate on a closed database"
                sid = m.create_session(title="重建后写入")
                got = m.get_session(sid)
                results.append(got is not None and got["title"] == "重建后写入")
            except Exception as e:  # pragma: no cover - 仅失败路径触发
                errors.append(e)
            finally:
                worker_done.set()

        t = threading.Thread(target=worker)
        t.start()
        try:
            assert started.wait(timeout=5), "worker 未在超时内建立首连"
            m.shutdown()  # 关闭所有线程连接并自增代际
            shutdown_done.set()
            assert worker_done.wait(timeout=5), "worker 未在超时内完成"
            assert errors == []
            assert results == [True]
        finally:
            shutdown_done.set()
            t.join(timeout=5)
            m.shutdown()

    def test_repeated_shutdown_is_safe(self, tmp_path):
        m = ContextManager(db_path=str(tmp_path / "gen2.db"))
        _ = m.create_session(title="x")
        m.shutdown()
        m.shutdown()  # 二次关闭不抛异常
        # shutdown 后主线程自身仍可重新获取连接
        sid = m.create_session(title="reborn")
        assert m.get_session(sid)["title"] == "reborn"
        m.shutdown()