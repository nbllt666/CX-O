"""server.core.memory.hybrid_search (HybridSearch) 单元测试。

覆盖关键词打分、向量/关键词结果融合权重、search 过滤排序、降级回退与快捷入口。
运行：python -m pytest tests/test_hybrid_search.py -v
"""
import pytest

from server.core.memory.hybrid_search import HybridSearch, HybridSearchOptions, SearchResult


class FakeVectorStore:
    def __init__(self, results=None, raise_agent_id=False):
        self.results = results or []
        self.raise_agent_id = raise_agent_id
        self.calls = []

    async def search_similar(self, query_embedding, limit, memory_type=None, agent_id=None):
        self.calls.append((limit, memory_type, agent_id))
        if self.raise_agent_id and agent_id is not None:
            raise TypeError("agent_id not supported")
        return self.results


class FakeEmbedding:
    def __init__(self):
        self.calls = 0

    async def get_embedding(self, query):
        self.calls += 1
        return [0.1, 0.2]


class FakeSQLite:
    def __init__(self, results=None, raise_agent_id=False):
        self.results = results or []
        self.raise_agent_id = raise_agent_id
        self.calls = []

    def search_memories(self, query=None, memory_type=None, tags=None, limit=10, agent_id=None):
        self.calls.append((limit, memory_type, tags, agent_id))
        if self.raise_agent_id and agent_id is not None:
            raise TypeError("agent_id not supported")
        return self.results


@pytest.fixture
def hs():
    return HybridSearch(vector_store=None, sqlite_manager=None)


class TestKeywordScore:
    def test_query_present_high_score(self, hs):
        score = hs._calculate_keyword_score("python 教程", "python")
        assert score > 0.1

    def test_query_absent_low_score(self, hs):
        assert hs._calculate_keyword_score("完全无关的内容", "xyz") == 0.1

    def test_query_at_start(self, hs):
        s_start = hs._calculate_keyword_score("python is great", "python")
        s_end = hs._calculate_keyword_score("great language python", "python")
        assert s_start >= s_end

    def test_case_insensitive(self, hs):
        assert hs._calculate_keyword_score("HELLO WORLD", "hello") > 0.1

    def test_empty_content(self, hs):
        assert hs._calculate_keyword_score("", "x") == 0.1


class TestMergeResults:
    def test_only_vector(self, hs):
        v = [SearchResult(1, "a", 0.8, "vector")]
        merged = hs._merge_results(v, [], 0.6, 0.4)
        assert len(merged) == 1
        assert merged[0].score == pytest.approx(0.8 * 0.6)
        assert merged[0].source == "vector"

    def test_only_keyword(self, hs):
        k = [SearchResult(2, "b", 0.5, "keyword")]
        merged = hs._merge_results([], k, 0.6, 0.4)
        assert len(merged) == 1
        assert merged[0].score == pytest.approx(0.5 * 0.4)
        assert merged[0].source == "keyword"

    def test_hybrid_overlap_weighted(self, hs):
        v = [SearchResult(1, "a", 0.8, "vector")]
        k = [SearchResult(1, "a", 0.6, "keyword")]
        merged = hs._merge_results(v, k, 0.6, 0.4)
        assert len(merged) == 1
        assert merged[0].score == pytest.approx(0.8 * 0.6 + 0.6 * 0.4)
        assert merged[0].source == "hybrid"

    def test_deduplicates_by_memory_id(self, hs):
        v = [SearchResult(1, "a", 0.8, "vector"), SearchResult(2, "b", 0.7, "vector")]
        k = [SearchResult(1, "a", 0.6, "keyword")]
        merged = hs._merge_results(v, k, 0.6, 0.4)
        assert len(merged) == 2


class TestSearch:
    @pytest.mark.asyncio
    async def test_keyword_only(self, hs):
        hs.sqlite_manager = FakeSQLite(
            results=[{"id": 1, "content": "python 教程", "type": "long_term"}]
        )
        opts = HybridSearchOptions(query="python", use_vector=False, use_keyword=True)
        results = await hs.search(opts)
        assert len(results) == 1
        assert results[0].source == "keyword"

    @pytest.mark.asyncio
    async def test_vector_only(self, hs):
        hs.vector_store = FakeVectorStore(
            results=[{"memory_id": 1, "content": "c", "score": 0.9}]
        )
        hs.embedding_model = FakeEmbedding()
        opts = HybridSearchOptions(query="q", use_vector=True, use_keyword=False)
        results = await hs.search(opts)
        assert len(results) == 1
        assert results[0].source == "vector"

    @pytest.mark.asyncio
    async def test_min_score_filtering(self, hs):
        hs.sqlite_manager = FakeSQLite(
            results=[{"id": 1, "content": "aa", "type": "long_term"}]
        )
        opts = HybridSearchOptions(
            query="aa", use_vector=False, use_keyword=True, min_score=0.5
        )
        results = await hs.search(opts)
        assert results == []

    @pytest.mark.asyncio
    async def test_limit(self, hs):
        hs.sqlite_manager = FakeSQLite(
            results=[{"id": i, "content": f"x{i}", "type": "long_term"} for i in range(5)]
        )
        opts = HybridSearchOptions(query="x", use_vector=False, use_keyword=True, limit=2)
        results = await hs.search(opts)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_vector_typeerror_fallback(self, hs):
        hs.vector_store = FakeVectorStore(
            results=[{"memory_id": 1, "content": "c", "score": 0.9}], raise_agent_id=True
        )
        hs.embedding_model = FakeEmbedding()
        opts = HybridSearchOptions(query="q", use_vector=True, use_keyword=False)
        results = await hs.search(opts)
        assert len(results) == 1
        # 首次调用带 agent_id('default')，回退调用（第2次）不带 agent_id
        assert hs.vector_store.calls[0][2] == "default"
        assert hs.vector_store.calls[1][2] is None

    @pytest.mark.asyncio
    async def test_semantic_search(self, hs):
        hs.vector_store = FakeVectorStore(
            results=[{"memory_id": 1, "content": "c", "score": 0.9}]
        )
        hs.embedding_model = FakeEmbedding()
        out = await hs.semantic_search("q", agent_id="agent_x")
        assert out[0]["memory_id"] == 1
        assert hs.vector_store.calls[0][2] == "agent_x"

    @pytest.mark.asyncio
    async def test_keyword_search_wrapper(self, hs):
        hs.sqlite_manager = FakeSQLite(
            results=[{"id": 1, "content": "python", "type": "long_term"}]
        )
        out = await hs.keyword_search("python")
        assert out[0]["memory_id"] == 1