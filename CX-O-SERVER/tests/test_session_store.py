"""server.core.session.store (SessionStore) 单元测试。

覆盖会话 CRUD、消息管理、过期清理、统计与全局实例。
运行：python -m pytest tests/test_session_store.py -v
"""
import pytest

from server.core.session.store import SessionStore, get_session_store
from server.core.session.models import SessionType


@pytest.fixture
def store(tmp_path):
    return SessionStore(db_path=str(tmp_path / "sessions.db"))


@pytest.fixture
def session(store):
    return store.create_session(workspace_id="ws1", title="测试会话")


class TestCreateSession:
    def test_creates_with_default_title(self, store):
        s = store.create_session()
        assert s.title == "新对话"
        assert s.session_type == SessionType.CHAT
        assert s.metadata == {}

    def test_creates_with_given_fields(self, store):
        s = store.create_session(
            workspace_id="ws2",
            title="定制",
            user_id="u1",
            session_type=SessionType.MEMORY,
            metadata={"a": 1},
        )
        assert s.workspace_id == "ws2"
        assert s.title == "定制"
        assert s.user_id == "u1"
        assert s.metadata == {"a": 1}

    def test_expires_in_days(self, store):
        s = store.create_session(expires_in_days=7)
        assert s.expires_at is not None


class TestGetSession:
    def test_returns_session(self, store, session):
        got = store.get_session(session.id)
        assert got.id == session.id
        assert got.title == "测试会话"
        assert got.workspace_id == "ws1"

    def test_unknown_returns_none(self, store):
        assert store.get_session("nonexistent") is None


class TestGetSessions:
    def test_filter_by_workspace(self, store):
        a = store.create_session(workspace_id="wsA")
        b = store.create_session(workspace_id="wsB")
        sessions = store.get_sessions(workspace_id="wsA")
        ids = [s.id for s in sessions]
        assert a.id in ids
        assert b.id not in ids

    def test_filter_by_type(self, store):
        a = store.create_session(session_type=SessionType.CHAT)
        b = store.create_session(session_type=SessionType.MEMORY)
        sessions = store.get_sessions(session_type=SessionType.MEMORY)
        ids = [s.id for s in sessions]
        assert b.id in ids
        assert a.id not in ids

    def test_active_only_excludes_inactive(self, store, session):
        other = store.create_session()
        store.update_session(other.id, is_active=False)
        sessions = store.get_sessions()
        ids = [s.id for s in sessions]
        assert session.id in ids
        assert other.id not in ids

    def test_limit_offset(self, store):
        for _ in range(5):
            store.create_session()
        all_sessions = store.get_sessions(limit=50)
        page = store.get_sessions(limit=2, offset=0)
        assert len(page) == 2
        assert len(all_sessions) == 5


class TestUpdateSession:
    def test_update_fields(self, store, session):
        ok = store.update_session(session.id, title="新标题", summary="摘要")
        assert ok is True
        got = store.get_session(session.id)
        assert got.title == "新标题"
        assert got.summary == "摘要"

    def test_update_metadata(self, store, session):
        store.update_session(session.id, metadata={"k": "v"})
        assert store.get_session(session.id).metadata == {"k": "v"}

    def test_no_updates_returns_false(self, store, session):
        assert store.update_session(session.id) is False

    def test_unknown_returns_false(self, store):
        assert store.update_session("nope", title="x") is False


class TestDeleteSession:
    def test_soft_delete(self, store, session):
        assert store.delete_session(session.id, soft_delete=True) is True
        assert store.get_session(session.id) is not None  # 软删除仍可读
        assert store.get_sessions(active_only=True) == []

    def test_hard_delete(self, store, session):
        assert store.delete_session(session.id, soft_delete=False) is True
        assert store.get_session(session.id) is None

    def test_unknown_returns_false(self, store):
        assert store.delete_session("nope") is False


class TestMessages:
    def test_add_increments_count(self, store, session):
        store.add_message(session.id, "user", "你好")
        store.add_message(session.id, "assistant", "嗨")
        got = store.get_session(session.id)
        assert got.message_count == 2

    def test_get_messages_ordered(self, store, session):
        store.add_message(session.id, "user", "1")
        store.add_message(session.id, "assistant", "2")
        msgs = store.get_messages(session.id)
        assert [m.content for m in msgs] == ["1", "2"]

    def test_get_messages_limit(self, store, session):
        for i in range(5):
            store.add_message(session.id, "user", str(i))
        msgs = store.get_messages(session.id, limit=2)
        assert len(msgs) == 2
        assert msgs[0].content == "0"

    def test_delete_message_soft(self, store, session):
        m = store.add_message(session.id, "user", "x")
        store.delete_message(m.id, soft_delete=True)
        assert store.get_messages(session.id) == []
        assert len(store.get_messages(session.id, include_deleted=True)) == 1


class TestExpired:
    def test_get_expired_sessions(self, store):
        exp = store.create_session(expires_in_days=-1)
        not_exp = store.create_session()
        expired = store.get_expired_sessions()
        ids = [s.id for s in expired]
        assert exp.id in ids
        assert not_exp.id not in ids

    def test_cleanup(self, store):
        exp = store.create_session(expires_in_days=-1)
        count = store.cleanup_expired_sessions()
        assert count == 1
        assert store.get_session(exp.id) is None


class TestStatistics:
    def test_empty(self, store):
        stats = store.get_statistics()
        assert stats.total_sessions == 0
        assert stats.total_messages == 0
        assert stats.avg_messages_per_session == 0

    def test_after_activity(self, store, session):
        store.add_message(session.id, "user", "a")
        store.add_message(session.id, "assistant", "b")
        stats = store.get_statistics()
        assert stats.total_sessions == 1
        assert stats.active_sessions == 1
        assert stats.total_messages == 2
        assert stats.avg_messages_per_session == 2.0


class TestSingleton:
    def test_same_instance(self, tmp_path):
        a = get_session_store(db_path=str(tmp_path / "a.db"))
        b = get_session_store(db_path=str(tmp_path / "a.db"))
        assert a is b