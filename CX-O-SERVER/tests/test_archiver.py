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

    @pytest.mark.asyncio
    async def test_merge_atomic_rollback_on_failure(self, archiver, mgr):
        """合并中途注入异常（merge_records INSERT 失败）→ 整体回滚。

        原子性保证：主记忆内容/标签/metadata 与被合并记忆的软删标记均保持
        合并前状态，merge_records 无残留行（修复前的两阶段写会产生半合并）。
        """
        m1 = mgr.write_memory("主记忆内容", tags=["a"])
        m2 = mgr.write_memory("次记忆内容", tags=["b"])

        conn = mgr._get_connection()
        # DB 级故障注入：merge_records 的 INSERT 一律 RAISE(ABORT)，迫使合并事务中途失败
        conn.execute(
            "CREATE TRIGGER test_inject_merge_fail "
            "BEFORE INSERT ON merge_records "
            "BEGIN SELECT RAISE(ABORT, 'injected merge failure'); END"
        )
        conn.commit()

        r = await archiver.merge_duplicate_memories([m1, m2])
        assert r.success is False

        # 清理注入触发器，恢复连接可用性
        conn.execute("DROP TRIGGER test_inject_merge_fail")
        conn.commit()

        # 主记忆未被修改：内容/标签原样，metadata 无合并标记
        primary = mgr.get_memory(m1)
        assert primary["content"] == "主记忆内容"
        assert primary["tags"] == ["a"]
        assert "is_merged" not in primary["metadata"]
        assert "merged_from" not in primary["metadata"]

        # 被合并记忆未被软删除：metadata 无 merged_into
        secondary = mgr.get_memory(m2, include_deleted=True)
        assert secondary["is_deleted"] is False
        assert "merged_into" not in secondary["metadata"]

        # merge_records 无残留行
        row = conn.execute("SELECT COUNT(*) FROM merge_records").fetchone()
        assert row[0] == 0


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


class TestTwoPhaseTransaction:
    """第十轮修复: 两阶段事务化 + sqlite 同步段 to_thread 卸载的行为验证。

    - archive_memory / archive_of_archives 的 LLM 压缩收集（await）必须全部
      在进入同步事务段之前完成，事务段内无任何 await；
    - 同步 sqlite 段经 asyncio.to_thread 卸载到工作线程，事件循环不再被阻塞。
    """

    @pytest.mark.asyncio
    async def test_archive_memory_runs_in_worker_thread(self, archiver, mgr):
        """archive_memory 的 sqlite 写段经 to_thread 卸载：执行线程 ≠ 事件循环线程。"""
        import threading

        loop_thread = threading.get_ident()
        seen_threads = []

        original_sync = archiver._archive_memory_sync

        def spy_sync(*args, **kwargs):
            # 本函数在 asyncio.to_thread 的工作线程中执行
            seen_threads.append(threading.get_ident())
            return original_sync(*args, **kwargs)

        archiver._archive_memory_sync = spy_sync

        mid = mgr.write_memory("线程卸载验证记忆")
        rec = await archiver.archive_memory(mid, target_level=1)

        assert rec is not None
        assert seen_threads, "事务段未被调用"
        assert seen_threads[0] != loop_thread

    @pytest.mark.asyncio
    async def test_archive_memory_get_memory_in_worker_thread(self, archiver, mgr):
        """archive_memory 阶段1 的 get_memory 读同样在非事件循环线程执行。"""
        import threading

        loop_thread = threading.get_ident()
        seen_threads = []

        mgr_get_memory = mgr.get_memory

        def spy_get_memory(memory_id, *args, **kwargs):
            seen_threads.append(threading.get_ident())
            return mgr_get_memory(memory_id, *args, **kwargs)

        mgr.get_memory = spy_get_memory

        mid = mgr.write_memory("读路径线程卸载验证")
        rec = await archiver.archive_memory(mid)

        assert rec is not None
        assert seen_threads and seen_threads[0] != loop_thread

    @pytest.mark.asyncio
    async def test_archive_of_archives_compresses_before_txn(self, archiver, mgr, monkeypatch):
        """两阶段顺序：全部 _compress_content 收集完成后才进入同步事务段。"""
        import asyncio

        mid = mgr.write_memory("两阶段顺序验证内容")
        await archiver.archive_memory(mid, target_level=3)

        class CountingLLM:
            def __init__(self):
                self.calls = 0

            async def chat(self, messages, stream=False):
                self.calls += 1
                # 主动让出事件循环：若收集与事务段交错，此处会让问题显形
                await asyncio.sleep(0)
                return _Resp(f"二次压缩{self.calls}")

        llm = CountingLLM()
        archiver.llm_client = llm

        txn_calls = {"n": 0}
        original_txn = archiver._insert_second_level_archives_sync

        def spy_txn(rows):
            # 进入事务段时，压缩收集（阶段1）必须已全部完成
            txn_calls["n"] += 1
            assert llm.calls == 1
            return original_txn(rows)

        monkeypatch.setattr(archiver, "_insert_second_level_archives_sync", spy_txn)

        results = await archiver.archive_of_archives(4)

        assert len(results) == 1
        assert results[0]["archive_level"] == 4
        assert llm.calls == 1
        assert txn_calls["n"] == 1

    @pytest.mark.asyncio
    async def test_archive_of_archives_rollback_on_insert_failure(self, archiver, mgr):
        """事务段 INSERT 失败注入 → 整体回滚，无半提交的二级归档行，且连接可复用。"""
        mid = mgr.write_memory("二次归档回滚验证")
        await archiver.archive_memory(mid, target_level=3)

        conn = mgr._get_connection()
        # DB 级故障注入：archive_records 的 INSERT 一律 RAISE(ABORT)
        conn.execute(
            "CREATE TRIGGER test_inject_aoa_fail "
            "BEFORE INSERT ON archive_records "
            "BEGIN SELECT RAISE(ABORT, 'injected aoa failure'); END"
        )
        conn.commit()

        # 失败返回 []（与旧实现对外行为一致）
        assert await archiver.archive_of_archives(4) == []

        # 事务段已整体回滚：级别 4 无残留行
        row = conn.execute(
            "SELECT COUNT(*) FROM archive_records WHERE archive_level = 4"
        ).fetchone()
        assert row[0] == 0

        # 清理注入触发器，验证回滚后连接可用、两阶段路径可正常重试
        conn.execute("DROP TRIGGER test_inject_aoa_fail")
        conn.commit()

        results = await archiver.archive_of_archives(4)
        assert len(results) == 1
        assert results[0]["original_memory_id"] == mid
        assert results[0]["archive_level"] == 4