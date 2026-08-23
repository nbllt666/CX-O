"""_DreamMixin（梦境记忆写入与生命周期，第 10 个 MemoryManager Mixin）单元测试。

通过 MemoryManager 单例（临时库 + 禁用后台线程）驱动验证：
- write_dream_memory 正常写入（字段断言：type/source/decay/permanent/metadata + create_dream audit）
- 断言拒写：permanent=True / 缺 dream_session_id / source 非 dream_engine → DreamIntegrityError 且不写入
- consolidate_dream：pending→confirmed（importance_score/λ 放缓/confirmed_at + audit）
- reject_dream：软删 + audit（details 含 reason）
- purge_dream_session：按会话批量软删 + rollback_dream_session audit
- list_dreams：按 state 过滤、软删排除、DESC 排序、limit、agent 隔离

运行：python -m pytest tests/test_dream_mixin.py -v
"""
import pytest

from server.core.memory.manager import MemoryManager
from server.core.memory.mixins.dream_mixin import DreamIntegrityError


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
    db_path = str(tmp_path / "memories.db")
    m = MemoryManager(db_path=db_path)
    yield m
    m.shutdown()
    MemoryManager._instance = None


def _dream_meta(session_id="sess-1", **overrides):
    meta = {
        "dream_session_id": session_id,
        "source": "dream_engine",
        "lucidity_score": 0.8,
        "emotion_shift": {"from": "平静", "to": "好奇"},
    }
    meta.update(overrides)
    return meta


def _audit_rows(mgr, operation, session_id=None):
    conn = mgr._get_connection()
    cur = conn.cursor()
    if session_id is None:
        cur.execute(
            "SELECT * FROM audit_logs WHERE operation = ? ORDER BY id",
            (operation,),
        )
    else:
        cur.execute(
            "SELECT * FROM audit_logs WHERE operation = ? AND session_id = ? ORDER BY id",
            (operation, session_id),
        )
    rows = [dict(r) for r in cur.fetchall()]
    return rows


# ================================================================ write_dream_memory
class TestWriteDreamMemory:
    def test_write_and_field_assertions(self, mgr):
        mid = mgr.write_dream_memory(
            "梦见在海边捡到一颗发光的石头",
            "sess-1",
            _dream_meta(),
        )
        assert mid > 0
        mem = mgr.get_memory(mid)
        assert mem["type"] == "dream"
        assert mem["source"] == "dream_engine"
        assert mem["importance"] == 1
        assert mem["importance_score"] == 0.15
        assert mem["decay_type"] == "dream"
        assert mem["decay_params"] == {"alpha": 1.0, "lambda1": 0.8}
        assert mem["permanent"] is False
        # 强制 metadata 字段
        assert mem["metadata"]["dream_session_id"] == "sess-1"
        assert mem["metadata"]["source"] == "dream_engine"
        assert mem["metadata"]["is_ground_truth"] is False
        assert mem["metadata"]["consolidation_state"] == "pending"
        assert mem["metadata"]["surfaced_at"] is None
        assert mem["metadata"]["confirmed_at"] is None

    def test_write_forces_metadata_fields(self, mgr):
        # 调用方即使传入 True / 其它值，强制字段也以 Mixin 为准
        mid = mgr.write_dream_memory(
            "被强制覆盖的梦境",
            "sess-2",
            _dream_meta(
                session_id="sess-2",
                is_ground_truth=True,
                consolidation_state="confirmed",
                surfaced_at="2026-01-01T00:00:00",
                confirmed_at="2026-01-01T00:00:00",
            ),
        )
        mem = mgr.get_memory(mid)
        assert mem["metadata"]["is_ground_truth"] is False
        assert mem["metadata"]["consolidation_state"] == "pending"
        assert mem["metadata"]["surfaced_at"] is None
        assert mem["metadata"]["confirmed_at"] is None

    def test_write_audit_create_dream(self, mgr):
        mid = mgr.write_dream_memory(
            "一场关于旧城的梦",
            "sess-3",
            _dream_meta(session_id="sess-3"),
        )
        rows = _audit_rows(mgr, "create_dream")
        assert len(rows) == 1
        assert rows[0]["memory_id"] == mid
        assert rows[0]["session_id"] == "sess-3"
        assert rows[0]["operator"] == "system"
        details = __import__("json").loads(rows[0]["details"])
        assert details["agent_id"] == "default"
        assert details["dream_session_id"] == "sess-3"
        assert "旧城" in details["content_preview"]

    def test_dream_not_returned_by_non_dream_search(self, mgr):
        mgr.write_dream_memory("梦里的独白", "sess-4", _dream_meta(session_id="sess-4"))
        # 数据层按 type 软隔离：按其它 type 检索时梦境不出现（召回排除由 router 承接）
        results = mgr.search_memories(query="独白", memory_type="long_term")
        assert len(results) == 0
        # 梦境仍可按 type='dream' 定位
        assert len(mgr.search_memories(query="独白", memory_type="dream")) == 1


# ================================================================ 断言拒写
class TestWriteDreamAssertions:
    def test_permanent_true_raises_and_not_written(self, mgr):
        with pytest.raises(DreamIntegrityError):
            mgr.write_dream_memory("永久梦境？", "sess-1", _dream_meta(permanent=True))
        assert mgr.list_dreams() == []
        assert _audit_rows(mgr, "create_dream") == []

    def test_missing_dream_session_id_raises(self, mgr):
        meta = {"source": "dream_engine"}
        with pytest.raises(DreamIntegrityError):
            mgr.write_dream_memory("无会话梦境", "sess-1", meta)
        assert mgr.list_dreams() == []

    def test_dream_session_id_mismatch_raises(self, mgr):
        with pytest.raises(DreamIntegrityError):
            mgr.write_dream_memory("会话不符", "sess-A", _dream_meta(session_id="sess-B"))

    def test_source_not_dream_engine_raises(self, mgr):
        meta = _dream_meta(source="user")
        with pytest.raises(DreamIntegrityError):
            mgr.write_dream_memory("非引擎来源", "sess-1", meta)

    def test_metadata_none_raises(self, mgr):
        with pytest.raises(DreamIntegrityError):
            mgr.write_dream_memory("空元数据", "sess-1", None)


# ================================================================ consolidate_dream
class TestConsolidateDream:
    def test_consolidate_pending_to_confirmed(self, mgr):
        mid = mgr.write_dream_memory("待确认的梦", "sess-1", _dream_meta())
        assert mgr.consolidate_dream(mid) is True
        mem = mgr.get_memory(mid)
        assert mem["metadata"]["consolidation_state"] == "confirmed"
        assert mem["metadata"]["confirmed_at"] is not None
        assert mem["importance_score"] == 0.4
        assert mem["decay_params"] == {"alpha": 1.0, "lambda1": 0.25}
        # audit
        rows = _audit_rows(mgr, "consolidate_dream")
        assert len(rows) == 1
        assert rows[0]["memory_id"] == mid

    def test_consolidate_custom_importance(self, mgr):
        mid = mgr.write_dream_memory("自定义固化分", "sess-1", _dream_meta())
        assert mgr.consolidate_dream(mid, confirmed_importance=0.6) is True
        assert mgr.get_memory(mid)["importance_score"] == 0.6

    def test_consolidate_surfaced_allowed(self, mgr):
        mid = mgr.write_dream_memory("已浮出的梦", "sess-1", _dream_meta())
        # 手工置为 surfaced 状态
        conn = mgr._get_connection()
        cur = conn.cursor()
        mem = mgr.get_memory(mid)
        mem["metadata"]["consolidation_state"] = "surfaced"
        cur.execute(
            "UPDATE memories SET metadata=? WHERE id=?",
            (__import__("json").dumps(mem["metadata"]), mid),
        )
        conn.commit()
        assert mgr.consolidate_dream(mid) is True
        assert mgr.get_memory(mid)["metadata"]["consolidation_state"] == "confirmed"

    def test_consolidate_already_confirmed_noop(self, mgr):
        mid = mgr.write_dream_memory("已固化的梦", "sess-1", _dream_meta())
        assert mgr.consolidate_dream(mid) is True
        assert mgr.consolidate_dream(mid) is False  # 第二次 no-op

    def test_consolidate_non_dream_returns_false(self, mgr):
        mid = mgr.write_memory("普通记忆", memory_type="long_term")
        assert mgr.consolidate_dream(mid) is False

    def test_consolidate_missing_returns_false(self, mgr):
        assert mgr.consolidate_dream(99999) is False


# ================================================================ reject_dream
class TestRejectDream:
    def test_reject_soft_deletes_and_audits(self, mgr):
        mid = mgr.write_dream_memory("被否定的梦", "sess-1", _dream_meta())
        assert mgr.reject_dream(mid, reason="用户否定该联想") is True
        # 默认查询不可见
        assert mgr.get_memory(mid) is None
        # 含已删除可见且为软删
        mem = mgr.get_memory(mid, include_deleted=True)
        assert mem["is_deleted"] is True
        # deleted_at 已落库（_row_to_memory 不暴露该列，直接查库校验）
        conn = mgr._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT deleted_at FROM memories WHERE id=?", (mid,))
        assert cur.fetchone()["deleted_at"] is not None
        # audit 含 reason
        rows = _audit_rows(mgr, "reject_dream")
        assert len(rows) == 1
        assert rows[0]["memory_id"] == mid
        assert "用户否定该联想" in rows[0]["details"]

    def test_reject_empty_reason(self, mgr):
        mid = mgr.write_dream_memory("无因否定", "sess-1", _dream_meta())
        assert mgr.reject_dream(mid) is True
        rows = _audit_rows(mgr, "reject_dream")
        assert __import__("json").loads(rows[0]["details"])["reason"] == ""

    def test_reject_non_dream_returns_false(self, mgr):
        mid = mgr.write_memory("普通记忆")
        assert mgr.reject_dream(mid) is False
        assert mgr.get_memory(mid) is not None

    def test_reject_missing_returns_false(self, mgr):
        assert mgr.reject_dream(99999) is False

    def test_reject_twice_second_noop(self, mgr):
        mid = mgr.write_dream_memory("二次否定", "sess-1", _dream_meta())
        assert mgr.reject_dream(mid) is True
        assert mgr.reject_dream(mid) is False


# ================================================================ purge_dream_session
class TestPurgeDreamSession:
    def test_purge_batch_soft_delete(self, mgr):
        ids_a = [
            mgr.write_dream_memory(f"梦境A-{i}", "sess-A", _dream_meta(session_id="sess-A"))
            for i in range(3)
        ]
        id_b = mgr.write_dream_memory("梦境B", "sess-B", _dream_meta(session_id="sess-B"))
        normal = mgr.write_memory("普通记忆")

        assert mgr.purge_dream_session("sess-A") == 3
        # A 会话梦境全部软删
        for mid in ids_a:
            assert mgr.get_memory(mid) is None
            assert mgr.get_memory(mid, include_deleted=True)["is_deleted"] is True
        # B 会话梦境与普通记忆不受影响
        assert mgr.get_memory(id_b) is not None
        assert mgr.get_memory(normal) is not None
        # audit 逐条记录
        rows = _audit_rows(mgr, "rollback_dream_session", session_id="sess-A")
        assert len(rows) == 3
        assert {r["memory_id"] for r in rows} == set(ids_a)

    def test_purge_no_match_returns_zero(self, mgr):
        assert mgr.purge_dream_session("sess-NONE") == 0

    def test_purge_skips_non_dream(self, mgr):
        mgr.write_memory("普通记忆")
        assert mgr.purge_dream_session("sess-NONE") == 0


# ================================================================ list_dreams
class TestListDreams:
    def test_list_only_dreams(self, mgr):
        mgr.write_dream_memory("梦境一", "sess-1", _dream_meta())
        mgr.write_memory("普通记忆")
        dreams = mgr.list_dreams()
        assert len(dreams) == 1
        assert dreams[0]["type"] == "dream"

    def test_list_filters_by_state(self, mgr):
        m1 = mgr.write_dream_memory("待确认", "sess-1", _dream_meta(session_id="sess-1"))
        m2 = mgr.write_dream_memory("待确认2", "sess-1", _dream_meta(session_id="sess-1"))
        m3 = mgr.write_dream_memory("已确认", "sess-1", _dream_meta(session_id="sess-1"))
        mgr.consolidate_dream(m3)

        confirmed = mgr.list_dreams(state="confirmed")
        assert [m["id"] for m in confirmed] == [m3]
        pending = mgr.list_dreams(state="pending")
        assert {m["id"] for m in pending} == {m1, m2}

    def test_list_excludes_soft_deleted(self, mgr):
        m1 = mgr.write_dream_memory("保留", "sess-1", _dream_meta())
        m2 = mgr.write_dream_memory("否定", "sess-1", _dream_meta())
        mgr.reject_dream(m2)
        ids = {m["id"] for m in mgr.list_dreams()}
        assert ids == {m1}

    def test_list_order_created_desc(self, mgr):
        old = mgr.write_dream_memory("旧梦境", "sess-1", _dream_meta())
        new = mgr.write_dream_memory("新梦境", "sess-1", _dream_meta())
        # 回填旧记忆的 created_at，保证排序可判定
        conn = mgr._get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE memories SET created_at=? WHERE id=?", ("2020-01-01T00:00:00", old))
        conn.commit()
        ids = [m["id"] for m in mgr.list_dreams()]
        assert ids == [new, old]

    def test_list_limit(self, mgr):
        for i in range(3):
            mgr.write_dream_memory(f"梦境{i}", "sess-1", _dream_meta())
        assert len(mgr.list_dreams(limit=2)) == 2
        assert len(mgr.list_dreams()) == 3

    def test_list_agent_isolation(self, mgr):
        mgr.write_dream_memory("default 的梦", "sess-1", _dream_meta())
        mgr.write_dream_memory("alice 的梦", "sess-1", _dream_meta(), agent_id="alice")
        assert len(mgr.list_dreams()) == 1
        assert len(mgr.list_dreams(agent_id="alice")) == 1
