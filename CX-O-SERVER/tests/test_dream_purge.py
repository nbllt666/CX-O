"""server/autonomy/dream/purge.py（DreamPurgeJob 自动清除）单测。

覆盖（红线 R4：只动 type='dream'，全部软删 + 审计）：
1. 超 dream_ttl_hours 且未确认（pending/surfaced）的梦境软删（reason=purged_ttl_expired）
2. 已确认的梦境即使超 TTL 也不清除；新鲜 pending 不受影响
3. importance_score < purge_threshold 的梦境软删（reason=purged_low_importance）
4. dream_buffer 过期候选清理（purged_buffer 计数）
5. 普通记忆（非 dream）永不误伤；返回统计结构正确

运行：python -m pytest tests/test_dream_purge.py -q
"""
import json
import sqlite3
from datetime import datetime, timedelta

import pytest

from server.autonomy.dream.buffer import DreamBuffer
from server.autonomy.dream.config import DreamConfig
from server.autonomy.dream.purge import DreamPurgeJob
from server.core.memory.manager import MemoryManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """每个用例独立的临时数据库 MemoryManager（禁用后台线程）。"""
    monkeypatch.setattr(MemoryManager, "_start_cleanup_task", lambda self: None)

    def _noop_init(self):
        self.archiver = None
        self.deduplication_engine = None
        self.vectorization_queue = None

    monkeypatch.setattr(MemoryManager, "_init_advanced_components", _noop_init)
    MemoryManager._instance = None
    m = MemoryManager(db_path=str(tmp_path / "memories.db"))
    yield m
    m.shutdown()
    MemoryManager._instance = None


@pytest.fixture
def buf(tmp_path):
    """每个用例独立的临时缓冲 SQLite。"""
    return DreamBuffer(db_path=str(tmp_path / "dream_buffer.db"))


def _dream_meta(session_id="sess-1", **overrides):
    meta = {
        "dream_session_id": session_id,
        "source": "dream_engine",
        "lucidity_score": 0.8,
    }
    meta.update(overrides)
    return meta


def _set_created_at(mgr, memory_id, dt):
    """回填 memories.created_at 为指定时间（模拟历史数据）。"""
    conn = mgr._get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE memories SET created_at=? WHERE id=?",
        (dt.isoformat(), memory_id),
    )
    conn.commit()


def _set_importance_score(mgr, memory_id, score):
    """回填 memories.importance_score（模拟低分梦境）。"""
    conn = mgr._get_connection()
    cur = conn.cursor()
    cur.execute("UPDATE memories SET importance_score=? WHERE id=?", (score, memory_id))
    conn.commit()


def _audit_reject_reasons(mgr):
    conn = mgr._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM audit_logs WHERE operation='reject_dream' ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    return [json.loads(r["details"])["reason"] for r in rows]


# ================================================================ TTL 过期清除
class TestPurgeTtlExpired:
    @pytest.mark.asyncio
    async def test_purge_expired_pending_soft_deletes(self, mgr, buf):
        old_id = mgr.write_dream_memory("过期未确认的梦", "sess-1", _dream_meta())
        fresh_id = mgr.write_dream_memory("新鲜的梦", "sess-2", _dream_meta(session_id="sess-2"))
        _set_created_at(mgr, old_id, datetime.now() - timedelta(days=10))
        _set_created_at(mgr, fresh_id, datetime.now() - timedelta(minutes=1))

        result = await DreamPurgeJob(mgr, buf).run()

        assert result == {"purged_memories": 1, "purged_buffer": 0}
        # 软删而非物理删除
        assert mgr.get_memory(old_id) is None
        assert mgr.get_memory(old_id, include_deleted=True)["is_deleted"] is True
        assert mgr.get_memory(fresh_id) is not None
        # 审计 reason 标注 TTL
        assert _audit_reject_reasons(mgr) == ["purged_ttl_expired"]

    @pytest.mark.asyncio
    async def test_purge_skips_confirmed_even_if_ttl_expired(self, mgr, buf):
        mid = mgr.write_dream_memory("已确认的旧梦", "sess-1", _dream_meta())
        mgr.consolidate_dream(mid)
        _set_created_at(mgr, mid, datetime.now() - timedelta(days=10))

        result = await DreamPurgeJob(mgr, buf).run()

        assert result["purged_memories"] == 0
        assert mgr.get_memory(mid) is not None

    @pytest.mark.asyncio
    async def test_purge_skips_surfaced_fresh(self, mgr, buf):
        # surfaced 未确认但未超 TTL → 不清除
        mid = mgr.write_dream_memory("已浮出的梦", "sess-1", _dream_meta())
        conn = mgr._get_connection()
        cur = conn.cursor()
        mem = mgr.get_memory(mid)
        mem["metadata"]["consolidation_state"] = "surfaced"
        cur.execute(
            "UPDATE memories SET metadata=? WHERE id=?",
            (json.dumps(mem["metadata"]), mid),
        )
        conn.commit()

        result = await DreamPurgeJob(mgr, buf).run()

        assert result["purged_memories"] == 0
        assert mgr.get_memory(mid) is not None


# ================================================================ 低分清除
class TestPurgeLowImportance:
    @pytest.mark.asyncio
    async def test_purge_low_importance_only(self, mgr, buf):
        low = mgr.write_dream_memory("低分梦境", "sess-1", _dream_meta())
        high = mgr.write_dream_memory("高分梦境", "sess-1", _dream_meta())
        _set_importance_score(mgr, low, 0.05)
        _set_importance_score(mgr, high, 0.6)

        result = await DreamPurgeJob(mgr, buf).run()

        assert result["purged_memories"] == 1
        assert mgr.get_memory(low) is None
        assert mgr.get_memory(low, include_deleted=True)["is_deleted"] is True
        assert mgr.get_memory(high) is not None
        assert _audit_reject_reasons(mgr) == ["purged_low_importance"]

    @pytest.mark.asyncio
    async def test_purge_custom_threshold(self, mgr, buf):
        cfg = DreamConfig(purge_threshold=0.5)
        mid = mgr.write_dream_memory("默认 0.15 分梦境", "sess-1", _dream_meta())

        result = await DreamPurgeJob(mgr, buf, config=cfg).run()

        assert result["purged_memories"] == 1
        assert mgr.get_memory(mid) is None

    @pytest.mark.asyncio
    async def test_purge_overlapping_ttl_and_low_score_no_double_count(self, mgr, buf):
        mid = mgr.write_dream_memory("既过期又低分", "sess-1", _dream_meta())
        _set_created_at(mgr, mid, datetime.now() - timedelta(days=10))
        _set_importance_score(mgr, mid, 0.01)

        result = await DreamPurgeJob(mgr, buf).run()

        # TTL 分支已清，低分分支不重复计数
        assert result["purged_memories"] == 1
        assert mgr.get_memory(mid, include_deleted=True)["is_deleted"] is True


# ================================================================ 缓冲过期清除
class TestPurgeBuffer:
    @pytest.mark.asyncio
    async def test_purge_expired_buffer_rows(self, mgr, buf):
        # 一条未过期缓冲
        buf.put({
            "dream_session_id": "sess-fresh",
            "agent_id": "default",
            "candidate_content": "新鲜候选",
            "lucidity_score": 0.8,
        })
        # 直接插入一条已过期缓冲行（模拟历史数据）
        past = datetime.now() - timedelta(days=1)
        conn = sqlite3.connect(buf.db_path)
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

        result = await DreamPurgeJob(mgr, buf).run()

        assert result["purged_memories"] == 0
        assert result["purged_buffer"] == 1
        remaining = buf.list()
        assert [i["dream_session_id"] for i in remaining] == ["sess-fresh"]


# ================================================================ 只动 dream
class TestPurgeSafety:
    @pytest.mark.asyncio
    async def test_purge_never_touches_non_dream(self, mgr, buf):
        normal = mgr.write_memory("普通记忆", memory_type="long_term")
        _set_created_at(mgr, normal, datetime.now() - timedelta(days=100))

        result = await DreamPurgeJob(mgr, buf).run()

        assert result["purged_memories"] == 0
        assert mgr.get_memory(normal) is not None
        assert _audit_reject_reasons(mgr) == []
