"""server.core.memory.manager (MemoryManager) 单元测试。

覆盖表名解析、记忆 CRUD、搜索（关键词/类型/标签/时间范围/分页）、
软/硬删除、恢复、统计、异步包装与 Agent 隔离。

因 MemoryManager 为单例且 __init__ 会启动清理线程与向量化队列，
fixture 中重置单例并禁用后台线程，使用 pytest tmp_path 独立临时库。
运行：python -m pytest tests/test_memory_manager.py -v
"""
import pytest

from server.core.memory.manager import MemoryManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """每个用例独立的临时数据库 MemoryManager（禁用后台线程）。"""
    # 禁用后台清理线程
    monkeypatch.setattr(MemoryManager, "_start_cleanup_task", lambda self: None)
    # 禁用高级组件初始化（归档器/去重引擎/向量化队列线程）
    def _noop_init(self):
        self.archiver = None
        self.deduplication_engine = None
        self.vectorization_queue = None

    monkeypatch.setattr(MemoryManager, "_init_advanced_components", _noop_init)

    # 重置单例
    MemoryManager._instance = None
    db_path = str(tmp_path / "memories.db")
    m = MemoryManager(db_path=db_path)
    yield m
    m.shutdown()
    MemoryManager._instance = None


def _write(mgr, content, **kwargs):
    return mgr.write_memory(content=content, **kwargs)


class TestTableName:
    def test_default_returns_memories(self, mgr):
        assert mgr._get_table_name("default") == "memories"

    def test_empty_returns_memories(self, mgr):
        assert mgr._get_table_name("") == "memories"

    def test_agent_prefixed(self, mgr):
        assert mgr._get_table_name("agent_x") == "memories_agent_x"

    def test_agent_illegal_chars_sanitized(self, mgr):
        assert mgr._get_table_name("a-b/c") == "memories_a_b_c"

    def test_agent_digit_prefix_gets_prefix(self, mgr):
        assert mgr._get_table_name("123") == "memories_agent_123"


class TestWriteGet:
    def test_write_and_get(self, mgr):
        mid = _write(mgr, "今天学习了 Python")
        assert mid > 0
        mem = mgr.get_memory(mid)
        assert mem is not None
        assert mem["content"] == "今天学习了 Python"
        assert mem["type"] == "long_term"
        assert mem["importance"] == 3
        assert mem["is_deleted"] is False

    def test_write_permanent(self, mgr):
        mid = _write(mgr, "重要记忆", permanent=True, importance=5)
        mem = mgr.get_memory(mid)
        assert mem["permanent"] is True
        assert mem["decay_type"] == "zero"
        assert mem["importance_score"] == 1.0

    def test_get_missing_returns_none(self, mgr):
        assert mgr.get_memory(99999) is None

    def test_write_with_tags_and_metadata(self, mgr):
        mid = _write(mgr, "带标签的记忆", tags=["python", "学习"], metadata={"source": "test"})
        mem = mgr.get_memory(mid)
        assert mem["tags"] == ["python", "学习"]
        assert mem["metadata"] == {"source": "test"}


class TestSearch:
    def test_search_by_content(self, mgr):
        _write(mgr, "Alpha 记忆内容")
        _write(mgr, "Beta 记忆内容")
        results = mgr.search_memories(query="Alpha")
        assert len(results) == 1
        assert results[0]["content"] == "Alpha 记忆内容"

    def test_search_by_type(self, mgr):
        _write(mgr, "短期", memory_type="short_term")
        _write(mgr, "长期", memory_type="long_term")
        results = mgr.search_memories(memory_type="long_term")
        assert len(results) == 1
        assert results[0]["content"] == "长期"

    def test_search_by_tags(self, mgr):
        _write(mgr, "带 tag 的记忆", tags=["unique_tag"])
        _write(mgr, "无 tag 的记忆")
        results = mgr.search_memories(tags=["unique_tag"])
        assert len(results) == 1
        assert results[0]["content"] == "带 tag 的记忆"

    def test_search_time_range_today(self, mgr):
        _write(mgr, "今天的记忆")
        results = mgr.search_memories(time_range="today")
        assert len(results) == 1

    def test_search_pagination_limit_offset(self, mgr):
        for i in range(5):
            _write(mgr, f"记忆内容 {i}")
        page1 = mgr.search_memories(limit=2, offset=0)
        page2 = mgr.search_memories(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        ids = {m["id"] for m in page1 + page2}
        assert len(ids) == 4

    def test_search_query_escaping(self, mgr):
        _write(mgr, "100% 完成度")
        results = mgr.search_memories(query="100%")
        assert len(results) == 1

    def test_search_excludes_deleted(self, mgr):
        mid = _write(mgr, "将被删除的记忆")
        mgr.delete_memory(mid)
        results = mgr.search_memories(query="将被删除")
        assert len(results) == 0


class TestUpdate:
    def test_update_content(self, mgr):
        mid = _write(mgr, "旧内容")
        assert mgr.update_memory(mid, new_content="新内容") is True
        assert mgr.get_memory(mid)["content"] == "新内容"

    def test_update_tags_and_importance(self, mgr):
        mid = _write(mgr, "更新记忆")
        assert mgr.update_memory(mid, new_tags=["新标签"], new_importance=5) is True
        mem = mgr.get_memory(mid)
        assert mem["tags"] == ["新标签"]
        assert mem["importance"] == 5

    def test_update_no_fields_returns_false(self, mgr):
        mid = _write(mgr, "内容")
        assert mgr.update_memory(mid) is False

    def test_update_missing_returns_false(self, mgr):
        assert mgr.update_memory(99999, new_content="x") is False


class TestDeleteRestore:
    def test_soft_delete(self, mgr):
        mid = _write(mgr, "软删除记忆")
        assert mgr.delete_memory(mid, soft_delete=True) is True
        assert mgr.get_memory(mid) is None
        # 含已删除仍可读
        assert mgr.get_memory(mid, include_deleted=True) is not None

    def test_hard_delete(self, mgr):
        mid = _write(mgr, "硬删除记忆")
        assert mgr.delete_memory(mid, soft_delete=False) is True
        assert mgr.get_memory(mid, include_deleted=True) is None

    def test_restore(self, mgr):
        mid = _write(mgr, "恢复记忆")
        mgr.delete_memory(mid)
        assert mgr.restore_memory(mid) is True
        assert mgr.get_memory(mid) is not None

    def test_delete_missing_returns_false(self, mgr):
        assert mgr.delete_memory(99999) is False


class TestStatistics:
    def test_statistics_counts(self, mgr):
        _write(mgr, "普通记忆1")
        _write(mgr, "普通记忆2", memory_type="short_term")
        permanent = _write(mgr, "永久记忆", permanent=True)
        deleted = _write(mgr, "待删除")
        mgr.delete_memory(deleted)

        stats = mgr.get_statistics()
        assert stats["total"] == 3
        # 永久记忆也写入 memories 表且 type 默认为 long_term
        assert stats["by_type"] == {"long_term": 2, "short_term": 1}
        assert stats["soft_deleted"] == 1
        assert stats["permanent"] == 1


class TestAsyncWrappers:
    @pytest.mark.asyncio
    async def test_write_memory_async(self, mgr):
        mid = await mgr.write_memory_async("异步记忆")
        mem = await mgr.get_memory_async(mid)
        assert mem["content"] == "异步记忆"

    @pytest.mark.asyncio
    async def test_search_statistics_async(self, mgr):
        _write(mgr, "同步写入")
        results = await mgr.search_memories_async(query="同步")
        assert len(results) == 1
        stats = await mgr.get_statistics_async()
        assert stats["total"] == 1


class TestAgentIsolation:
    def test_agent_separate_tables(self, mgr):
        mid_a = _write(mgr, "Agent A 的记忆", agent_id="agent_a")
        _write(mgr, "Agent default 的记忆")

        # 指定 agent 读取
        mem = mgr.get_memory(mid_a, agent_id="agent_a")
        assert mem["content"] == "Agent A 的记忆"

        # 默认表搜索不包含 agent_a 的记忆
        results = mgr.search_memories(query="Agent", agent_id="default")
        assert all(m["content"] != "Agent A 的记忆" for m in results)

    def test_agent_table_name_created(self, mgr):
        _write(mgr, "x", agent_id="custom-agent")
        assert mgr._get_table_name("custom-agent") == "memories_custom_agent"


class TestRowToMemory:
    def test_row_with_json_parse_failure(self, mgr):
        mid = _write(mgr, "内容")
        conn = mgr._get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE memories SET metadata='{bad json', tags='[bad' WHERE id=?", (mid,))
        conn.commit()
        mem = mgr.get_memory(mid)
        # 解析失败降级为空值
        assert mem["metadata"] == {}
        assert mem["tags"] == []