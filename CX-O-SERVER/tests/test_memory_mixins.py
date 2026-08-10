"""MemoryManager mixins（permanent/batch/query/vector）单元测试。

通过 MemoryManager 单例（临时库 + 禁用后台线程）驱动验证以下 mixin：
- permanent_mixin：永久记忆写/读/列表/更新/删除（副模型无权删除）、行映射。
- batch_mixin：批量写/更新/删除/标签(add/remove/set)/归档及错误处理。
- query_mixin：过期会话清理、标签搜索、时间线、统计、会话记忆、按类型/情感/关系查询。
- vector_mixin：向量未启用时同步/更新/删除安全跳过、语义/混合搜索回退、启用标记。

运行：python -m pytest tests/test_memory_mixins.py -v
"""
import pytest

from server.core.memory.manager import MemoryManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
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


def _write(mgr, content, **kwargs):
    return mgr.write_memory(content=content, **kwargs)


# ================================================================ permanent_mixin
class TestPermanentMixin:
    def test_write_and_get(self, mgr):
        pid = mgr.write_permanent_memory("永久记忆", tags=["核心"])
        assert pid > 0
        pm = mgr.get_permanent_memory(pid)
        assert pm["content"] == "永久记忆"
        assert pm["tags"] == ["核心"]
        assert pm["importance_score"] == 1.0
        assert pm["verified"] is True

    def test_write_source_secondary(self, mgr):
        pid = mgr.write_permanent_memory("副模型", source="secondary", is_from_main=False)
        pm = mgr.get_permanent_memory(pid)
        assert pm["source"] == "secondary"

    def test_get_missing_returns_none(self, mgr):
        assert mgr.get_permanent_memory(99999) is None

    def test_list_permanent(self, mgr):
        mgr.write_permanent_memory("a", tags=["t1"])
        mgr.write_permanent_memory("b", tags=["t2"])
        all_ = mgr.get_permanent_memories()
        assert len(all_) == 2
        tagged = mgr.get_permanent_memories(tags=["t1"])
        assert len(tagged) == 1
        assert tagged[0]["content"] == "a"

    def test_update_permanent(self, mgr):
        pid = mgr.write_permanent_memory("旧")
        assert mgr.update_permanent_memory(pid, content="新", tags=["x"]) is True
        pm = mgr.get_permanent_memory(pid)
        assert pm["content"] == "新"
        assert pm["tags"] == ["x"]

    def test_update_permanent_no_fields_returns_false(self, mgr):
        pid = mgr.write_permanent_memory("内容")
        assert mgr.update_permanent_memory(pid) is False

    def test_delete_permanent_secondary_denied(self, mgr):
        pid = mgr.write_permanent_memory("内容")
        assert mgr.delete_permanent_memory(pid, is_from_main=False) is False
        assert mgr.get_permanent_memory(pid) is not None

    def test_delete_permanent_main(self, mgr):
        pid = mgr.write_permanent_memory("内容")
        assert mgr.delete_permanent_memory(pid, is_from_main=True) is True
        assert mgr.get_permanent_memory(pid) is None

    def test_row_parse_failure_falls_back(self, mgr):
        pid = mgr.write_permanent_memory("内容")
        conn = mgr._get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE permanent_memories SET metadata='{bad', tags='[bad' WHERE id=?", (pid,))
        conn.commit()
        pm = mgr.get_permanent_memory(pid)
        assert pm["metadata"] == {}
        assert pm["tags"] == []


# ================================================================ batch_mixin
class TestBatchMixin:
    def test_batch_write(self, mgr):
        res = mgr.batch_write_memories([
            {"content": "a", "type": "long_term"},
            {"content": "b", "type": "short_term"},
        ])
        assert res["success"] == 2
        assert res["failed"] == 0
        assert len(res["memory_ids"]) == 2

    def test_batch_write_error_continue(self, mgr, monkeypatch):
        # 使第二条写入抛错，验证容错路径（默认不中断）
        calls = {"n": 0}

        def _flaky_write(self_, content, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom")
            return 1

        monkeypatch.setattr(MemoryManager, "write_memory", _flaky_write)
        res = mgr.batch_write_memories([{"content": "ok"}, {"content": "bad"}])
        assert res["success"] == 1
        assert res["failed"] == 1
        assert res["errors"][0] == "boom"

    def test_batch_write_error_raises(self, mgr, monkeypatch):
        def _raise(self_, content, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(MemoryManager, "write_memory", _raise)
        with pytest.raises(RuntimeError):
            mgr.batch_write_memories([{"content": "x"}], raise_on_error=True)

    def test_batch_update(self, mgr):
        m1 = _write(mgr, "旧1")
        m2 = _write(mgr, "旧2")
        res = mgr.batch_update_memories([
            {"memory_id": m1, "content": "新1"},
            {"memory_id": m2, "content": "新2"},
        ])
        assert res["success"] == 2
        assert mgr.get_memory(m1)["content"] == "新1"

    def test_batch_update_missing_id(self, mgr):
        res = mgr.batch_update_memories([{"content": "x"}])
        assert res["failed"] == 1

    def test_batch_update_not_found(self, mgr):
        res = mgr.batch_update_memories([{"memory_id": 99999, "content": "x"}])
        assert res["failed"] == 1
        assert res["errors"][0] == "Memory 99999 not found"

    def test_batch_delete(self, mgr):
        m1 = _write(mgr, "a")
        m2 = _write(mgr, "b")
        res = mgr.batch_delete_memories([m1, m2])
        assert res["success"] == 2
        assert mgr.get_memory(m1) is None

    def test_batch_delete_not_found(self, mgr):
        res = mgr.batch_delete_memories([99999])
        assert res["failed"] == 1

    def test_batch_update_tags_add(self, mgr):
        m1 = _write(mgr, "a", tags=["t1"])
        res = mgr.batch_update_tags([m1], ["t2"], operation="add")
        assert res["updated_count"] == 1
        assert set(mgr.get_memory(m1)["tags"]) == {"t1", "t2"}

    def test_batch_update_tags_remove(self, mgr):
        m1 = _write(mgr, "a", tags=["t1", "t2"])
        res = mgr.batch_update_tags([m1], ["t1"], operation="remove")
        assert res["updated_count"] == 1
        assert mgr.get_memory(m1)["tags"] == ["t2"]

    def test_batch_update_tags_set(self, mgr):
        m1 = _write(mgr, "a", tags=["t1"])
        res = mgr.batch_update_tags([m1], ["t3"], operation="set")
        assert res["updated_count"] == 1
        assert mgr.get_memory(m1)["tags"] == ["t3"]

    def test_batch_update_tags_missing(self, mgr):
        res = mgr.batch_update_tags([99999], ["t"], operation="add")
        assert res["failed_count"] == 1

    def test_batch_archive(self, mgr):
        m1 = _write(mgr, "a")
        m2 = _write(mgr, "b")
        res = mgr.batch_archive_memories([m1, m2])
        assert res["archived_count"] == 2
        assert mgr.get_memory(m1)["archived_at"] is not None

    def test_batch_archive_missing(self, mgr):
        res = mgr.batch_archive_memories([99999])
        assert res["failed_count"] == 1


# ================================================================ query_mixin
class TestQueryMixin:
    def test_search_by_tag(self, mgr):
        _write(mgr, "带标签", tags=["unique_q"])
        _write(mgr, "无标签")
        results = mgr.search_by_tag("unique_q")
        assert len(results) == 1
        assert results[0]["content"] == "带标签"

    def test_get_memory_statistics(self, mgr):
        _write(mgr, "a", memory_type="long_term")
        _write(mgr, "b", memory_type="short_term", tags=["t"], emotion_score=0.5)
        stats = mgr.get_memory_statistics()
        assert stats["status"] == "success"
        assert stats["total_memories"] == 2
        assert stats["by_type"]["long_term"] == 1
        assert stats["by_type"]["short_term"] == 1
        assert "t" in dict(stats["top_tags"])

    def test_get_memory_timeline(self, mgr):
        _write(mgr, "a")
        result = mgr.get_memory_timeline(days=30)
        assert result["status"] == "success"
        assert result["total_days"] >= 1

    def test_get_memories_by_type(self, mgr):
        _write(mgr, "a", memory_type="long_term")
        _write(mgr, "b", memory_type="short_term")
        long_list = mgr.get_memories_by_type("long_term")
        assert len(long_list) == 1
        assert long_list[0]["content"] == "a"

    def test_get_memories_by_type_permanent(self, mgr):
        _write(mgr, "永久", permanent=True)
        perms = mgr.get_memories_by_type("permanent")
        assert len(perms) == 1
        assert perms[0]["content"] == "永久"

    def test_get_memories_by_emotion(self, mgr):
        _write(mgr, "高情感", emotion_score=0.9)
        _write(mgr, "低情感", emotion_score=0.1)
        results = mgr.get_memories_by_emotion((0.5, 1.0))
        assert len(results) == 1
        assert results[0]["content"] == "高情感"

    def test_get_memory_relationships(self, mgr):
        m1 = _write(mgr, "a", tags=["共享"])
        _write(mgr, "b", tags=["共享"])
        _write(mgr, "c", tags=["其他"])
        rel = mgr.get_memory_relationships(m1)
        assert rel["status"] == "success"
        assert rel["total_relationships"] == 1
        assert rel["relationships"][0]["relation_type"] == "tag_similarity"

    def test_get_memory_relationships_missing(self, mgr):
        rel = mgr.get_memory_relationships(99999)
        assert rel["status"] == "error"

    def test_cleanup_old_sessions(self, mgr):
        m1 = _write(mgr, "短期", memory_type="short_term")
        conn = mgr._get_connection()
        cur = conn.cursor()
        # 回填 100 天前的创建时间，触发过期清理
        cur.execute("UPDATE memories SET created_at=? WHERE id=?",
                    ("2020-01-01T00:00:00", m1))
        conn.commit()
        res = mgr.cleanup_old_sessions(days=30)
        assert res["status"] == "success"
        assert res["cleaned_count"] == 1
        assert mgr.get_memory(m1) is None

    def test_cleanup_old_sessions_none(self, mgr):
        _write(mgr, "短期", memory_type="short_term")
        res = mgr.cleanup_old_sessions(days=30)
        assert res["cleaned_count"] == 0

    def test_get_session_memories(self, mgr):
        m1 = _write(mgr, "会话记忆")
        conn = mgr._get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO audit_logs (operation, memory_id, session_id, operator, details) VALUES (?,?,?,?,?)",
            ("create", m1, "sess_1", "system", "{}"),
        )
        conn.commit()
        results = mgr.get_session_memories("sess_1")
        assert len(results) == 1
        assert results[0]["content"] == "会话记忆"


# ================================================================ vector_mixin
class TestVectorIntegrationMixin:
    def test_is_vector_search_disabled_by_default(self, mgr):
        assert mgr.is_vector_search_enabled() is False

    def test_sync_vector_skips_when_disabled(self, mgr):
        assert mgr._sync_vector_for_memory(1, "内容", {"agent_id": "default"}) is False

    def test_update_vector_skips_when_disabled(self, mgr):
        assert mgr._update_vector_for_memory(1, "内容", {}) is False

    def test_delete_vector_skips_when_disabled(self, mgr):
        assert mgr._delete_vector_for_memory(1) is False

    @pytest.mark.asyncio
    async def test_semantic_search_falls_back(self, mgr):
        _write(mgr, "关键词内容")
        results = await mgr.semantic_search(query="关键词")
        assert len(results) == 1
        assert results[0]["content"] == "关键词内容"

    @pytest.mark.asyncio
    async def test_hybrid_search_falls_back(self, mgr):
        _write(mgr, "混合内容")
        results = await mgr.hybrid_search(query="混合")
        assert len(results) == 1
        assert results[0]["fallback"] is True

    def test_on_vectorization_complete_no_store(self, mgr):
        # 无向量存储/嵌入模型时静默跳过
        mgr.vectorization_queue = None
        mgr._on_vectorization_complete("1", "内容")  # 不应抛错

    def test_enable_vector_search_unsupported_backend(self, mgr):
        mgr.enable_vector_search(vector_backend="nope")
        assert mgr._vector_store is None