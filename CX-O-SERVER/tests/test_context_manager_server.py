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