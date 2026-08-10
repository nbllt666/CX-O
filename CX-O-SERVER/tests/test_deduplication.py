"""server.core.memory.deduplication (DeduplicationEngine) 单元测试。

覆盖 Jaccard 文本相似度计算、相似度缓存、相似记忆查找、
批量重复检测（相似图 + 连通分量）、去重组生成、无实现纯逻辑。

运行：python -m pytest tests/test_deduplication.py -v
"""
import pytest

from server.core.memory.deduplication import (
    DeduplicationEngine,
    DuplicateGroup,
    SimilarityRecord,
)


class FakeMemoryManager:
    def __init__(self, memories=None):
        self.memories = memories or {}

    def get_memory(self, memory_id):
        return self.memories.get(memory_id)

    def search_memories(self, memory_type=None, limit=10000, include_deleted=False):
        return list(self.memories.values())


def _mem(mid, content, created_at=""):
    return {"id": mid, "content": content, "created_at": created_at}


@pytest.fixture
def engine():
    return DeduplicationEngine(memory_manager=FakeMemoryManager(), threshold=0.8)


# ---------------------------------------------------------------- Jaccard
class TestTextSimilarity:
    def test_identical_texts(self, engine):
        assert engine._calculate_text_similarity("你好 世界", "你好 世界") == 1.0

    def test_empty_text(self, engine):
        assert engine._calculate_text_similarity("", "你好") == 0.0
        assert engine._calculate_text_similarity("你好", "") == 0.0

    def test_partial_overlap(self, engine):
        sim = engine._calculate_text_similarity("a b c", "a b d")
        assert sim == 2 / 4  # 交集 {a,b} / 并集 {a,b,c,d}

    def test_no_overlap(self, engine):
        assert engine._calculate_text_similarity("a b", "c d") == 0.0


# ---------------------------------------------------------------- 相似度与缓存
class TestCheckSimilarity:
    @pytest.mark.asyncio
    async def test_missing_memory_returns_zero(self, engine):
        assert await engine.check_similarity(1, 999) == 0.0

    @pytest.mark.asyncio
    async def test_caches_result(self, engine):
        engine.memory_manager.memories = {1: _mem(1, "a b c"), 2: _mem(2, "a b c")}
        r1 = await engine.check_similarity(1, 2)
        r2 = await engine.check_similarity(2, 1)  # 顺序无关，命中缓存
        assert r1 == 1.0
        assert r2 == 1.0
        assert len(engine._similarity_cache) == 1

    @pytest.mark.asyncio
    async def test_clear_cache(self, engine):
        engine.memory_manager.memories = {1: _mem(1, "a b"), 2: _mem(2, "a b")}
        await engine.check_similarity(1, 2)
        engine.clear_cache()
        assert engine._similarity_cache == {}


# ---------------------------------------------------------------- 相似记忆查找
class TestFindSimilar:
    @pytest.mark.asyncio
    async def test_finds_similar_above_threshold(self):
        mgr = FakeMemoryManager(
            {1: _mem(1, "a b c d", "2026-01-01"), 2: _mem(2, "a b c e", "2026-01-02")}
        )
        engine = DeduplicationEngine(memory_manager=mgr, threshold=0.5)
        records = await engine.find_similar_memories(1)
        assert len(records) == 1
        assert isinstance(records[0], SimilarityRecord)
        assert records[0].memory_id_1 == 1
        assert records[0].memory_id_2 == 2

    @pytest.mark.asyncio
    async def test_empty_result_when_no_match(self, engine):
        engine.memory_manager.memories = {1: _mem(1, "a"), 2: _mem(2, "b")}
        records = await engine.find_similar_memories(1, threshold=0.5)
        assert records == []

    @pytest.mark.asyncio
    async def test_sort_by_similarity_desc(self):
        mgr = FakeMemoryManager(
            {
                1: _mem(1, "a b c d"),
                2: _mem(2, "a b c d e f"),
                3: _mem(3, "x y z"),
                4: _mem(4, "a b c d e f g h i j"),
            }
        )
        engine = DeduplicationEngine(memory_manager=mgr, threshold=0.2)
        records = await engine.find_similar_memories(1)
        scores = [r.similarity_score for r in records]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------- 连通分量
class TestConnectedComponents:
    def test_isolated_nodes(self, engine):
        comps = engine._find_connected_components({1: set(), 2: set()})
        assert len(comps) == 2

    def test_linked_nodes(self, engine):
        comps = engine._find_connected_components({1: {2}, 2: {1}, 3: set()})
        assert len(comps) == 2
        sizes = sorted(len(c) for c in comps)
        assert sizes == [1, 2]


# ---------------------------------------------------------------- 批量去重
class TestBatchDetect:
    @pytest.mark.asyncio
    async def test_detects_duplicate_group(self):
        mgr = FakeMemoryManager(
            {
                1: _mem(1, "a b c d", "2026-01-01"),
                2: _mem(2, "a b c d", "2026-01-02"),
                3: _mem(3, "x y z", "2026-01-03"),
            }
        )
        engine = DeduplicationEngine(memory_manager=mgr, threshold=0.5)
        groups = await engine.detect_duplicates_batch(memory_ids=[1, 2, 3])
        assert len(groups) == 1
        group = groups[0]
        assert isinstance(group, DuplicateGroup)
        assert set(group.memory_ids) == {1, 2}
        # 最早创建时间的记忆为代表
        assert group.canonical_id == 1

    @pytest.mark.asyncio
    async def test_no_duplicates(self, engine):
        engine.memory_manager.memories = {1: _mem(1, "a"), 2: _mem(2, "b")}
        groups = await engine.detect_duplicates_batch(memory_ids=[1, 2], threshold=0.5)
        assert groups == []

    @pytest.mark.asyncio
    async def test_group_id_generation(self, engine):
        gid = engine._generate_group_id([3, 1, 2])
        assert isinstance(gid, str) and len(gid) == 16


# ---------------------------------------------------------------- 去重组查询
class TestGroupQueries:
    def test_get_duplicate_groups(self, engine):
        engine._duplicate_groups["g1"] = DuplicateGroup(group_id="g1", memory_ids=[1, 2])
        groups = engine.get_duplicate_groups()
        assert len(groups) == 1

    def test_get_group_by_memory(self, engine):
        engine._duplicate_groups["g1"] = DuplicateGroup(group_id="g1", memory_ids=[1, 2])
        assert engine.get_duplicate_group_by_memory(2).group_id == "g1"
        assert engine.get_duplicate_group_by_memory(99) is None

    def test_to_dict_roundtrip(self, engine):
        g = DuplicateGroup(group_id="g1", memory_ids=[1, 2], canonical_id=1)
        d = g.to_dict()
        assert d["group_id"] == "g1"
        assert d["canonical_id"] == 1


# ---------------------------------------------------------------- 记录相似性
class TestRecordSimilarity:
    @pytest.mark.asyncio
    async def test_below_threshold_no_log(self, engine):
        # threshold=0.8，0.5 低于阈值，不应抛错
        await engine.record_search_similarity(1, 2, 0.5)

    @pytest.mark.asyncio
    async def test_above_threshold(self, engine):
        await engine.record_search_similarity(1, 2, 0.9)