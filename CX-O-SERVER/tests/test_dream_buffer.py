"""CX-O-Dream 缓冲隔离模块（server/autonomy/dream/buffer.py）单测。

覆盖：
1. put 后 list 返回 pending，expires_at = created_at + dream_ttl_hours
2. get / get_by_session 正确返回
3. mark_decision 为 rejected 且 expires_at 约 now+30 天（保留审计），decision_reason 落库
4. mark_decision 为 approved/pending 不改 expires_at
5. purge_expired 删除过期行并返回删除数
6. list 按 decision 过滤
7. 非法 decision 抛 ValueError

运行：python -m pytest tests/test_dream_buffer.py -q
"""
import sqlite3
from datetime import datetime, timedelta

import pytest

from server.autonomy.dream.buffer import DreamBuffer
from server.autonomy.dream.config import DreamConfig


def _sample_candidate(**overrides):
    """构造一条梦境候选（对齐 buffer.put 契约字段）。"""
    candidate = {
        "dream_session_id": "sess-001",
        "agent_id": "default",
        "candidate_content": "梦见在海边捡到一颗会发光的石头",
        "associated_memories": [{"id": 1, "content": "昨天傍晚在海边散步"}],
        "associated_entities": ["海边", "石头"],
        "lucidity_score": 0.8,
        "emotion_shift": {"from": "平静", "to": "好奇"},
    }
    candidate.update(overrides)
    return candidate


# ================================================================ put + list
class TestPutAndList:
    def test_put_returns_id_and_lists_pending(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buffer_id = buf.put(_sample_candidate())
        assert isinstance(buffer_id, int) and buffer_id > 0

        items = buf.list()
        assert len(items) == 1
        item = items[0]
        assert item["id"] == buffer_id
        assert item["decision"] == "pending"
        assert item["dream_session_id"] == "sess-001"
        assert item["candidate_content"] == "梦见在海边捡到一颗会发光的石头"
        assert item["associated_memories"] == [{"id": 1, "content": "昨天傍晚在海边散步"}]
        assert item["associated_entities"] == ["海边", "石头"]
        assert item["lucidity_score"] == 0.8
        assert item["emotion_shift"] == {"from": "平静", "to": "好奇"}

    def test_put_sets_created_and_expires_by_ttl(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        before = datetime.now()
        buf.put(_sample_candidate())
        item = buf.list()[0]

        created = datetime.fromisoformat(item["created_at"])
        expires = datetime.fromisoformat(item["expires_at"])
        assert before <= created <= datetime.now()
        # 默认 dream_ttl_hours=72
        assert expires - created == timedelta(hours=72)

    def test_put_honors_custom_ttl(self, tmp_path):
        cfg = DreamConfig(dream_ttl_hours=24)
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"), config=cfg)
        buf.put(_sample_candidate())
        item = buf.list()[0]
        created = datetime.fromisoformat(item["created_at"])
        expires = datetime.fromisoformat(item["expires_at"])
        assert expires - created == timedelta(hours=24)

    def test_put_defaults_agent_id_and_json_fields(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buf.put(_sample_candidate(agent_id=None, associated_memories=None, emotion_shift=None))
        item = buf.list()[0]
        assert item["agent_id"] == "default"
        assert item["associated_memories"] is None
        assert item["emotion_shift"] is None

    def test_list_order_by_created_desc(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buf.put(_sample_candidate(dream_session_id="sess-1", candidate_content="第一条"))
        buf.put(_sample_candidate(dream_session_id="sess-2", candidate_content="第二条"))
        items = buf.list()
        assert [i["candidate_content"] for i in items] == ["第二条", "第一条"]


# ================================================================ get / get_by_session
class TestGet:
    def test_get_returns_matching_record(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buffer_id = buf.put(_sample_candidate())
        item = buf.get(buffer_id)
        assert item is not None
        assert item["id"] == buffer_id
        assert item["dream_session_id"] == "sess-001"

    def test_get_missing_returns_none(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        assert buf.get(9999) is None

    def test_get_by_session_returns_all_for_session(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buf.put(_sample_candidate(dream_session_id="sess-A", candidate_content="A1"))
        buf.put(_sample_candidate(dream_session_id="sess-A", candidate_content="A2"))
        buf.put(_sample_candidate(dream_session_id="sess-B", candidate_content="B1"))

        session_a = buf.get_by_session("sess-A")
        assert len(session_a) == 2
        assert {i["candidate_content"] for i in session_a} == {"A1", "A2"}
        assert all(i["dream_session_id"] == "sess-A" for i in session_a)

        session_b = buf.get_by_session("sess-B")
        assert [i["candidate_content"] for i in session_b] == ["B1"]

        assert buf.get_by_session("sess-NONE") == []


# ================================================================ mark_decision
class TestMarkDecision:
    def test_rejected_sets_expires_at_about_30_days(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buffer_id = buf.put(_sample_candidate())

        assert buf.mark_decision(buffer_id, "rejected", reason="用户否定该联想") is True

        item = buf.get(buffer_id)
        assert item["decision"] == "rejected"
        assert item["decision_reason"] == "用户否定该联想"
        expires = datetime.fromisoformat(item["expires_at"])
        delta = expires - datetime.now()
        # 约 now+30 天（容差 1 分钟）
        assert timedelta(days=30) - timedelta(minutes=1) <= delta <= timedelta(days=30) + timedelta(minutes=1)

    def test_rejected_honors_custom_retention_days(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buffer_id = buf.put(_sample_candidate())
        buf.mark_decision(buffer_id, "rejected", reason="r", retention_days=7)
        expires = datetime.fromisoformat(buf.get(buffer_id)["expires_at"])
        delta = expires - datetime.now()
        assert timedelta(days=7) - timedelta(minutes=1) <= delta <= timedelta(days=7) + timedelta(minutes=1)

    def test_approved_does_not_change_expires_at(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buffer_id = buf.put(_sample_candidate())
        original_expires = buf.get(buffer_id)["expires_at"]

        assert buf.mark_decision(buffer_id, "approved", reason="用户确认") is True
        item = buf.get(buffer_id)
        assert item["decision"] == "approved"
        assert item["decision_reason"] == "用户确认"
        assert item["expires_at"] == original_expires

    def test_pending_mark_keeps_expires_at(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buffer_id = buf.put(_sample_candidate())
        original_expires = buf.get(buffer_id)["expires_at"]
        buf.mark_decision(buffer_id, "pending", reason="重新挂起")
        item = buf.get(buffer_id)
        assert item["decision"] == "pending"
        assert item["expires_at"] == original_expires

    def test_invalid_decision_raises_value_error(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buffer_id = buf.put(_sample_candidate())
        with pytest.raises(ValueError):
            buf.mark_decision(buffer_id, "invalid")

    def test_mark_missing_id_returns_false(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        assert buf.mark_decision(9999, "rejected") is False


# ================================================================ purge_expired
class TestPurgeExpired:
    def test_purge_removes_expired_rows_and_returns_count(self, tmp_path):
        db_path = str(tmp_path / "dream_buffer.db")
        buf = DreamBuffer(db_path=db_path)
        buf.put(_sample_candidate())

        # 直接插入一条已过期记录（模拟历史数据）
        past = datetime.now() - timedelta(days=1)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                INSERT INTO dream_buffer
                    (dream_session_id, agent_id, candidate_content,
                     associated_memories, associated_entities, lucidity_score,
                     emotion_shift, decision, decision_reason, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sess-old",
                    "default",
                    "过期候选",
                    None,
                    None,
                    0.0,
                    None,
                    "pending",
                    None,
                    past.isoformat(),
                    past.isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        # 未过期记录不删除
        assert buf.purge_expired() == 1
        remaining = buf.list()
        assert len(remaining) == 1
        assert remaining[0]["dream_session_id"] == "sess-001"

    def test_purge_with_future_now_deletes_fresh_rows(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buf.put(_sample_candidate())
        future = datetime.now() + timedelta(days=10)
        assert buf.purge_expired(now=future) == 1
        assert buf.list() == []

    def test_purge_no_expired_returns_zero(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buf.put(_sample_candidate())
        assert buf.purge_expired() == 0


# ================================================================ list 按 decision 过滤
class TestListDecisionFilter:
    def test_list_filters_by_decision(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        id_1 = buf.put(_sample_candidate(candidate_content="候选一"))
        id_2 = buf.put(_sample_candidate(candidate_content="候选二"))
        buf.put(_sample_candidate(candidate_content="候选三"))
        # 候选一 approved，候选二 rejected，候选三保持 pending
        buf.mark_decision(id_1, "approved", reason="确认")
        buf.mark_decision(id_2, "rejected", reason="否定")

        approved = buf.list(decision="approved")
        assert [i["candidate_content"] for i in approved] == ["候选一"]
        rejected = buf.list(decision="rejected")
        assert [i["candidate_content"] for i in rejected] == ["候选二"]
        pending = buf.list(decision="pending")
        assert [i["candidate_content"] for i in pending] == ["候选三"]

    def test_list_agent_isolation(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        buf.put(_sample_candidate(agent_id="default"))
        buf.put(_sample_candidate(agent_id="alice"))
        assert len(buf.list(agent_id="default")) == 1
        assert len(buf.list(agent_id="alice")) == 1
        assert len(buf.list()) == 1


# ================================================================ count 总匹配数（分页 total）
class TestCount:
    def test_count_all_matching(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        for i in range(5):
            buf.put(_sample_candidate(candidate_content=f"候选{i}"))
        assert buf.count() == 5
        assert buf.count(agent_id="default") == 5
        assert buf.count(agent_id="alice") == 0

    def test_count_filters_by_decision(self, tmp_path):
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        id_1 = buf.put(_sample_candidate(candidate_content="候选一"))
        id_2 = buf.put(_sample_candidate(candidate_content="候选二"))
        buf.put(_sample_candidate(candidate_content="候选三"))
        buf.mark_decision(id_1, "approved", reason="确认")
        buf.mark_decision(id_2, "rejected", reason="否定")
        assert buf.count(decision="pending") == 1
        assert buf.count(decision="approved") == 1
        assert buf.count(decision="rejected") == 1
        assert buf.count(decision="approved", agent_id="alice") == 0

    def test_count_ignores_pagination_limits(self, tmp_path):
        """count 是总匹配数，不受 list 的 limit/offset 影响（供分页 total 使用）。"""
        buf = DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))
        for i in range(25):
            buf.put(_sample_candidate(candidate_content=f"候选{i}"))
        page = buf.list(limit=10, offset=0)
        assert len(page) == 10
        assert buf.count() == 25
