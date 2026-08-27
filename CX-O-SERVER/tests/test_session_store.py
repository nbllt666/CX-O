"""server.core.session.store (SessionStore) 单元测试。

覆盖会话 CRUD、消息管理、过期清理、统计与全局实例。
H2（第四轮体检 E组）追加：独立库路径解析、跨 schema 列名访问交叉场景、
游标式长期未访问清理、软删回减计数、外键级联。
运行：python -m pytest tests/test_session_store.py -v
"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from server.core.session.store import (
    SessionStore,
    get_session_store,
    get_tuner_session_db_path,
)
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


# --------------------------------------------------------------------------- #
# H2（第四轮体检 E组）追加验证
# --------------------------------------------------------------------------- #
class TestTunerSessionDbPath:
    """条目A/6: 独立库路径解析——env 覆盖 > 项目根归一化默认。"""

    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TUNER_SESSION_DB", str(tmp_path / "env_tuner.db"))
        assert get_tuner_session_db_path() == str(tmp_path / "env_tuner.db")

    def test_default_resolves_to_project_root_data(self, monkeypatch):
        monkeypatch.delenv("TUNER_SESSION_DB", raising=False)
        from server.config import _PROJECT_ROOT

        p = Path(get_tuner_session_db_path())
        assert p.is_absolute()
        assert p.parent == _PROJECT_ROOT / "data"
        assert p.name == "tuner_sessions.db"

    def test_default_singleton_uses_independent_db(self, monkeypatch, tmp_path):
        """条目A: 单例缺省走独立库名 data/tuner_sessions.db（env 重定向到 tmp 防真实落盘）。"""
        import server.core.session.store as store_mod

        # 默认相对路径常量静态断言（归一化行为已由上一用例覆盖）
        assert store_mod.DEFAULT_TUNER_SESSIONS_DB == "data/tuner_sessions.db"

        monkeypatch.setenv("TUNER_SESSION_DB", str(tmp_path / "tuner.db"))
        old = store_mod._session_store
        store_mod._session_store = None
        try:
            s = get_session_store()
            assert Path(s.db_path) == tmp_path / "tuner.db"
            assert Path(s.db_path).name != "sessions.db"
        finally:
            store_mod._session_store = old


class TestCrossSchemaColumnAccess:
    """H2 验证①: 列名访问在跨 schema 交叉场景下不串位。

    模拟历史 bug 现场：SessionStore（13列表）先建，ContextManager（10列假设）
    后读写同一文件。旧实现 SELECT * row[N] 位置索引必然串位（row[4] 读到
    session_type='chat'）；列名访问必须命中正确列。
    """

    def test_context_manager_reads_13col_table_without_misalignment(self, tmp_path):
        from server.core.context.manager import ContextManager

        db = str(tmp_path / "cross.db")
        store = SessionStore(db_path=db)  # 先建者：13列表
        s = store.create_session(title="交叉会话")
        store.add_message(s.id, "user", "问题")
        store.add_message(s.id, "assistant", "回答")

        cm = ContextManager(db_path=db)  # 另一家代码：CREATE IF NOT EXISTS no-op
        try:
            got = cm.get_session(s.id)
            assert got is not None
            # 旧实现下 created_at 会串位读到 'chat'、message_count 读到时间串；
            # 列名访问必须命中正确列——created_at 为合法 ISO 时间字符串
            assert got["title"] == "交叉会话"
            assert isinstance(got["created_at"], str) and got["created_at"] != "chat"
            datetime.fromisoformat(got["created_at"])  # 可解析
            assert got["message_count"] == 2
            msgs = cm.get_messages(s.id)
            assert [m["content"] for m in msgs] == ["问题", "回答"]
            assert msgs[0]["role"] == "user"
        finally:
            cm.shutdown()


class TestSoftDeleteDecrement:
    """H2 条目3: 软删消息同事务回减 message_count。"""

    def test_soft_delete_decrements_count(self, store, session):
        m1 = store.add_message(session.id, "user", "a")
        store.add_message(session.id, "user", "b")
        assert store.get_session(session.id).message_count == 2

        store.delete_message(m1.id, soft_delete=True)
        assert store.get_session(session.id).message_count == 1

    def test_soft_delete_missing_message_no_change(self, store, session):
        store.add_message(session.id, "user", "a")
        before = store.get_session(session.id).message_count
        store.delete_message("no-such-message", soft_delete=True)
        assert store.get_session(session.id).message_count == before


class TestCascadeHardDelete:
    """H2 条目5: foreign_keys=ON 下硬删父行级联删除 messages 子行。"""

    def test_hard_delete_session_removes_messages(self, store, session):
        store.add_message(session.id, "user", "x")
        assert store.delete_session(session.id, soft_delete=False) is True

        with sqlite3.connect(store.db_path) as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE session_id = ?", (session.id,)
            ).fetchone()[0]
        assert n == 0


class TestDeleteSessionsLastAccessedBefore:
    """H2 验证②+条目4: 游标循环删干净不跳项、无孤儿消息。"""

    def _backdate(self, store, session_ids, days_ago=40):
        old_iso = (datetime.now() - timedelta(days=days_ago)).isoformat()
        with sqlite3.connect(store.db_path) as conn:
            conn.executemany(
                "UPDATE sessions SET last_accessed_at = ? WHERE id = ?",
                [(old_iso, sid) for sid in session_ids],
            )
            conn.commit()

    def test_multi_batch_cursor_deletes_all_old_keep_new(self, tmp_path):
        db = str(tmp_path / "cursor.db")
        store = SessionStore(db_path=db)

        old_ids, new_ids, msg_ids = [], [], []
        # 交错创建新旧会话；page_size=2 强制多批循环（共12条 -> ≥6批）
        for i in range(12):
            s = store.create_session(title=f"s{i}")
            m = store.add_message(s.id, "user", f"msg{i}")
            (old_ids if i % 2 == 0 else new_ids).append(s.id)
            msg_ids.append((s.id, m.id))
        self._backdate(store, old_ids)

        cutoff = datetime.now() - timedelta(days=30)
        deleted = store.delete_sessions_last_accessed_before(cutoff, page_size=2)

        assert deleted == len(old_ids) == 6
        remaining_ids = {s.id for s in store.get_sessions(active_only=False, limit=100)}
        assert set(old_ids) & remaining_ids == set()   # 陈旧的全删干净（不跳项）
        assert remaining_ids == set(new_ids)           # 新鲜的完整保留
        # 游标循环结束后无陈旧残留可再删（第二遍删 0 条）
        assert store.delete_sessions_last_accessed_before(cutoff, page_size=2) == 0

        # 无孤儿消息：被删会话的消息全部消失，保留会话的消息仍在
        with sqlite3.connect(db) as conn:
            orphan_n = sum(
                conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ?", (sid,)
                ).fetchone()[0]
                for sid in old_ids
            )
            kept_n = sum(
                conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE session_id = ?", (sid,)
                ).fetchone()[0]
                for sid in new_ids
            )
        assert orphan_n == 0
        assert kept_n == len(new_ids)

    def test_empty_db_returns_zero(self, store):
        cutoff = datetime.now() - timedelta(days=30)
        assert store.delete_sessions_last_accessed_before(cutoff) == 0