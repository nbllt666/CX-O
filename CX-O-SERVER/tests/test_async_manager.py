"""server.core.memory.async_manager (AsyncMemoryManager) 单元测试。

用 aiosqlite 真实临时库覆盖初始化、记忆 CRUD、搜索筛选、批量写入、
统计、永久记忆 CRUD、衰减同步与统计、关闭连接。

运行：python -m pytest tests/test_async_manager.py -v
"""
import pytest
import pytest_asyncio

from server.core.memory.async_manager import AsyncMemoryManager


@pytest_asyncio.fixture
async def amgr(tmp_path):
    """独立的临时库 AsyncMemoryManager 实例。"""
    mgr = AsyncMemoryManager(db_path=str(tmp_path / "async_memories.db"))
    await mgr.initialize()
    yield mgr
    await mgr.close()


class TestInit:
    @pytest.mark.asyncio
    async def test_initialize_creates_db(self, amgr):
        assert amgr._initialized is True
        assert amgr._pool is not None

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, amgr):
        await amgr.initialize()
        await amgr.initialize()
        assert amgr._initialized is True

    @pytest.mark.asyncio
    async def test_close_resets_state(self, amgr):
        await amgr.close()
        assert amgr._pool is None
        assert amgr._initialized is False


class TestWriteGet:
    @pytest.mark.asyncio
    async def test_write_and_get(self, amgr):
        mid = await amgr.write_memory("你好世界", memory_type="long_term", importance=5)
        assert mid > 0
        mem = await amgr.get_memory(mid)
        assert mem["content"] == "你好世界"
        assert mem["memory_type"] == "long_term"
        assert mem["importance"] == 5
        assert mem["is_deleted"] is False

    @pytest.mark.asyncio
    async def test_write_tags_metadata_permanent(self, amgr):
        mid = await amgr.write_memory(
            "带标签", tags=["python"], metadata={"k": "v"}, permanent=True
        )
        mem = await amgr.get_memory(mid)
        assert mem["tags"] == ["python"]
        assert mem["metadata"] == {"k": "v"}
        assert mem["permanent"] is True

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, amgr):
        assert await amgr.get_memory(99999) is None

    @pytest.mark.asyncio
    async def test_get_hides_deleted(self, amgr):
        mid = await amgr.write_memory("待删")
        await amgr.delete_memory(mid, hard=False)
        assert await amgr.get_memory(mid) is None
        assert await amgr.get_memory(mid, include_deleted=True) is not None


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_keywords(self, amgr):
        await amgr.write_memory("Alpha 内容")
        await amgr.write_memory("Beta 内容")
        result = await amgr.search_memories(keywords="Alpha")
        assert len(result) == 1
        assert result[0]["content"] == "Alpha 内容"

    @pytest.mark.asyncio
    async def test_search_filters_type_importance_agent(self, amgr):
        await amgr.write_memory("短", memory_type="short_term", importance=1, agent_id="a")
        await amgr.write_memory("长", memory_type="long_term", importance=5, agent_id="b")
        result = await amgr.search_memories(memory_type="long_term", importance=3, agent_id="b")
        assert len(result) == 1
        assert result[0]["content"] == "长"

    @pytest.mark.asyncio
    async def test_search_tags(self, amgr):
        await amgr.write_memory("带 tag", tags=["utag"])
        await amgr.write_memory("无 tag")
        result = await amgr.search_memories(tags=["utag"])
        assert len(result) == 1
        assert result[0]["content"] == "带 tag"

    @pytest.mark.asyncio
    async def test_search_pagination(self, amgr):
        for i in range(5):
            await amgr.write_memory(f"内容{i}", memory_type="short_term")
        page1 = await amgr.search_memories(limit=2, offset=0)
        page2 = await amgr.search_memories(limit=2, offset=2)
        ids = {m["id"] for m in page1 + page2}
        assert len(page1) == 2
        assert len(page2) == 2
        assert len(ids) == 4


class TestUpdateDelete:
    @pytest.mark.asyncio
    async def test_update_content_and_importance(self, amgr):
        mid = await amgr.write_memory("旧")
        assert await amgr.update_memory(mid, content="新", importance=5) is True
        mem = await amgr.get_memory(mid)
        assert mem["content"] == "新"
        assert mem["importance"] == 5

    @pytest.mark.asyncio
    async def test_update_no_fields_returns_false(self, amgr):
        mid = await amgr.write_memory("x")
        assert await amgr.update_memory(mid) is False

    @pytest.mark.asyncio
    async def test_update_missing_returns_false(self, amgr):
        assert await amgr.update_memory(99999, content="x") is False

    @pytest.mark.asyncio
    async def test_delete_soft_and_hard(self, amgr):
        mid = await amgr.write_memory("软删")
        assert await amgr.delete_memory(mid, hard=False) is True
        mem = await amgr.get_memory(mid, include_deleted=True)
        assert mem["is_deleted"] is True
        mid2 = await amgr.write_memory("硬删")
        assert await amgr.delete_memory(mid2, hard=True) is True
        assert await amgr.get_memory(mid2, include_deleted=True) is None


class TestBatchStats:
    @pytest.mark.asyncio
    async def test_batch_write(self, amgr):
        result = await amgr.batch_write_memories(
            [
                {"content": "m1", "memory_type": "long_term"},
                {"content": "m2", "tags": ["t"]},
            ]
        )
        assert result["success"] == 2
        assert result["failed"] == 0
        assert await amgr.search_memories() and len(await amgr.search_memories()) == 2

    @pytest.mark.asyncio
    async def test_batch_write_missing_content_defaults(self, amgr):
        # 缺 content 时回退为空字符串，不报错
        result = await amgr.batch_write_memories([{"content": "有内容"}, {"memory_type": "long_term"}])
        assert result["success"] == 2
        assert result["failed"] == 0
        rows = await amgr.search_memories()
        contents = {r["content"] for r in rows}
        assert "" in contents

    @pytest.mark.asyncio
    async def test_statistics(self, amgr):
        await amgr.write_memory("类型1", memory_type="long_term", importance=5)
        await amgr.write_memory("类型2", memory_type="short_term", importance=2)
        stats = await amgr.get_memory_statistics()
        assert stats["total"] == 2
        assert stats["by_type"] == {"long_term": 1, "short_term": 1}
        assert stats["avg_importance"] == 3.5


class TestPermanentMemory:
    @pytest.mark.asyncio
    async def test_write_and_get_permanent(self, amgr):
        mid = await amgr.write_permanent_memory("永久记忆", tags=["p"], source="user")
        assert mid > 0
        mem = await amgr.get_permanent_memory(mid)
        assert mem["content"] == "永久记忆"
        assert mem["source"] == "user"

    @pytest.mark.asyncio
    async def test_list_permanent(self, amgr):
        await amgr.write_permanent_memory("p1")
        await amgr.write_permanent_memory("p2")
        rows = await amgr.get_permanent_memories()
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_update_permanent(self, amgr):
        mid = await amgr.write_permanent_memory("旧")
        assert await amgr.update_permanent_memory(mid, content="新", verified=True) is True
        mem = await amgr.get_permanent_memory(mid)
        assert mem["content"] == "新"
        assert mem["verified"] == 1

    @pytest.mark.asyncio
    async def test_delete_permanent(self, amgr):
        mid = await amgr.write_permanent_memory("删")
        assert await amgr.delete_permanent_memory(mid) is True
        assert await amgr.get_permanent_memory(mid) is None


class TestDecay:
    @pytest.mark.asyncio
    async def test_sync_decay_values(self, amgr):
        mid = await amgr.write_memory("衰减对象", importance=4, permanent=False)
        result = await amgr.sync_decay_values()
        assert result["updated"] >= 1
        mem = await amgr.get_memory(mid)
        assert mem["decay_score"] > 0

    @pytest.mark.asyncio
    async def test_decay_statistics(self, amgr):
        await amgr.write_memory("衰减", importance=3)
        stats = await amgr.get_decay_statistics()
        assert stats["total"] == 1
        assert stats["avg_decay"] >= 0


class TestHelpers:
    @pytest.mark.asyncio
    async def test_vector_search_not_enabled(self, amgr):
        assert await amgr.is_vector_search_enabled() is False

    @pytest.mark.asyncio
    async def test_hybrid_search_delegates(self, amgr):
        await amgr.write_memory("混合搜", memory_type="long_term")
        rows = await amgr.hybrid_search("混合搜")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_search_memories_3d(self, amgr):
        await amgr.write_memory("三维", memory_type="long_term")
        rows = await amgr.search_memories_3d("三维")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_recall_adds_emotion_intensity(self, amgr):
        mid = await amgr.write_memory("回忆")
        mem = await amgr.recall_memory(mid, emotion_intensity=0.7)
        assert mem["emotion_intensity"] == 0.7