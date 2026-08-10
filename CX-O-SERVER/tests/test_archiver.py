"""server.core.memory.archiver (AdvancedArchiver) 单元测试。

复用真实 MemoryManager（重置单例 + 禁用后台线程 + tmp_path 临时库），
覆盖归档、合并、归档的归档、统计与相似性记录。
运行：python -m pytest tests/test_archiver.py -v
"""
import pytest

from server.core.memory.archiver import AdvancedArchiver, ArchiveRecord, MergeResult
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
    m = MemoryManager(db_path=str(tmp_path / "memories.db"))
    yield m
    m.shutdown()
    MemoryManager._instance = None


@pytest.fixture
def archiver(mgr):
    return AdvancedArchiver(memory_manager=mgr)


class _Resp:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, text="压缩后的内容"):
        self.text = text
        self.calls = 0

    async def chat(self, messages, stream=False):
        self.calls += 1
        return _Resp(self.text)


class TestArchiveLevels:
    def test_defined_levels(self):
        assert set(AdvancedArchiver.ARCHIVE_LEVELS.keys()) == {0, 1, 2, 3, 4}
        assert AdvancedArchiver.ARCHIVE_LEVELS[0].name == "活跃"
        assert AdvancedArchiver.ARCHIVE_LEVELS[4].name == "深度归档"


class TestArchiveMemory:
    @pytest.mark.asyncio
    async def test_archive_creates_record(self, archiver, mgr):
        mid = mgr.write_memory("这是一条需要归档的记忆内容ABC")
        rec = await archiver.archive_memory(mid, target_level=2)
        assert rec is not None
        assert isinstance(rec, ArchiveRecord)
        assert rec.original_memory_id == mid
        assert rec.archive_level == 2
        assert rec.compressed_content == "这是一条需要归档的记忆内容ABC"
        # 记忆被标记为已归档（archived_at 非空）
        mem = mgr.get_memory(mid)
        assert mem.get("archived_at") is not None

    @pytest.mark.asyncio
    async def test_archive_missing_memory(self, archiver):
        assert await archiver.archive_memory(99999) is None

    @pytest.mark.asyncio
    async def test_archive_with_llm_compresses(self, archiver, mgr):
        archiver.llm_client = FakeLLM("简明摘要")
        mid = mgr.write_memory("原始长内容" * 10)
        rec = await archiver.archive_memory(mid)
        assert rec.compressed_content == "简明摘要"
        assert rec.compression_metadata["compressed_length"] == len("简明摘要")
        assert archiver.llm_client.calls == 1

    @pytest.mark.asyncio
    async def test_archive_empty_content(self, archiver, mgr):
        mid = mgr.write_memory("")
        rec = await archiver.archive_memory(mid)
        assert rec is not None
        assert rec.compression_metadata["compression_ratio"] == 1.0


class TestCompressContent:
    @pytest.mark.asyncio
    async def test_no_llm_returns_original(self, archiver):
        assert await archiver._compress_content("你好", 1) == "你好"

    @pytest.mark.asyncio
    async def test_llm_returns_stripped(self, archiver):
        archiver.llm_client = FakeLLM("  压缩  ")
        assert await archiver._compress_content("原文", 2) == "压缩"

    @pytest.mark.asyncio
    async def test_llm_empty_falls_back(self, archiver):
        archiver.llm_client = FakeLLM("   ")
        assert await archiver._compress_content("原文", 1) == "原文"


class TestMergeMemories:
    @pytest.mark.asyncio
    async def test_merge_less_than_two(self, archiver):
        r = await archiver.merge_duplicate_memories([1])
        assert r.success is False
        assert "至少需要两个" in r.message

    @pytest.mark.asyncio
    async def test_simple_merge(self, archiver, mgr):
        m1 = mgr.write_memory("第一条记忆", tags=["a"])
        m2 = mgr.write_memory("第二条记忆", tags=["b"])
        r = await archiver.merge_duplicate_memories([m1, m2], strategy="smart")
        assert r.success is True
        assert r.merged_memory_id == m1  # 最早创建的作为主记忆
        assert set(r.merged_from) == {m1, m2}
        # 主记忆保留
        assert mgr.get_memory(m1)["content"] == "第一条记忆"
        # 次记忆被软删除
        assert mgr.get_memory(m2, include_deleted=True)["is_deleted"] is True

    @pytest.mark.asyncio
    async def test_smart_merge_with_llm(self, archiver, mgr):
        archiver.llm_client = FakeLLM("智能合并结果")
        m1 = mgr.write_memory("内容一")
        m2 = mgr.write_memory("内容二")
        r = await archiver.merge_duplicate_memories([m1, m2], strategy="smart")
        assert r.merged_content == "智能合并结果"
        assert archiver.llm_client.calls == 1

    @pytest.mark.asyncio
    async def test_merge_missing_memories(self, archiver, mgr):
        m1 = mgr.write_memory("唯一的记忆")
        r = await archiver.merge_duplicate_memories([m1, 99999])
        assert r.success is False


class TestArchiveOfArchives:
    @pytest.mark.asyncio
    async def test_no_archives_returns_empty(self, archiver):
        assert await archiver.archive_of_archives(4) == []

    @pytest.mark.asyncio
    async def test_archive_of_archives(self, archiver, mgr):
        mid = mgr.write_memory("要被二次压缩的记忆内容")
        await archiver.archive_memory(mid, target_level=3)
        results = await archiver.archive_of_archives(4)
        assert len(results) == 1
        assert results[0]["archive_level"] == 4
        assert results[0]["original_memory_id"] == mid


class TestStats:
    def test_empty_stats(self, archiver):
        stats = archiver.get_archive_stats()
        assert stats != {}
        assert stats["total_archived"] == 0
        assert stats["merge_count"] == 0
        assert "archive_levels" in stats

    @pytest.mark.asyncio
    async def test_stats_after_archive_and_merge(self, archiver, mgr):
        mid = mgr.write_memory("归档的记忆")
        await archiver.archive_memory(mid, target_level=1)
        m1 = mgr.write_memory("合并一")
        m2 = mgr.write_memory("合并二")
        await archiver.merge_duplicate_memories([m1, m2])
        stats = archiver.get_archive_stats()
        assert stats["total_archived"] == 1
        assert stats["merge_count"] == 1


class TestSimilarity:
    def test_record_similarity(self, archiver):
        archiver.record_similarity(2, 1, 0.9, is_duplicate=True)
        stats = archiver.get_archive_stats()
        assert stats["duplicate_count"] == 1

    def test_record_normalizes_order(self, archiver):
        archiver.record_similarity(5, 3, 0.5)
        conn = archiver.memory_manager._get_connection()
        row = conn.execute(
            "SELECT memory_id_1, memory_id_2 FROM similarity_records LIMIT 1"
        ).fetchone()
        conn.close()
        assert row[0] == 3
        assert row[1] == 5