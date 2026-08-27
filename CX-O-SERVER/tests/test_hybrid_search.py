"""server.core.memory.hybrid_search (HybridSearch) 单元测试。

覆盖关键词打分、向量/关键词结果融合权重、search 过滤排序、降级回退与快捷入口，
以及 M-D5 评分字段透传与 H14 零向量防护。
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


class TestFieldPassThrough:
    """M-D5: keyword/vector 通道须把 sqlite 行的评分字段透传进 SearchResult。"""

    @pytest.mark.asyncio
    async def test_keyword_channel_passthrough(self, hs):
        hs.sqlite_manager = FakeSQLite(
            results=[
                {
                    "id": 1,
                    "content": "python 教程",
                    "type": "long_term",
                    "importance": 4,
                    "importance_score": 0.82,
                    "created_at": "2026-01-02T03:04:05",
                    "reactivation_count": 3,
                }
            ]
        )
        opts = HybridSearchOptions(query="python", use_vector=False, use_keyword=True)
        results = await hs.search(opts)
        r = results[0]
        assert r.importance == 4
        assert r.importance_score == pytest.approx(0.82)
        assert r.created_at == "2026-01-02T03:04:05"
        assert r.reactivation_count == 3

    @pytest.mark.asyncio
    async def test_vector_channel_passthrough(self, hs):
        hs.vector_store = FakeVectorStore(
            results=[
                {
                    "memory_id": 9,
                    "content": "c",
                    "score": 0.9,
                    "importance_score": 0.7,
                    "created_at": "2025-12-01T00:00:00",
                    "reactivation_count": 2,
                }
            ]
        )
        hs.embedding_model = FakeEmbedding()
        opts = HybridSearchOptions(query="q", use_vector=True, use_keyword=False)
        results = await hs.search(opts)
        assert results[0].created_at == "2025-12-01T00:00:00"
        assert results[0].reactivation_count == 2
        assert results[0].importance_score == pytest.approx(0.7)

    def test_merge_fills_missing_fields(self, hs):
        """hybrid 重叠合并时不覆盖已有值、缺失时从另一通道补齐。"""
        v = [
            SearchResult(
                1, "a", 0.8, "vector",
                importance_score=None, created_at=None,
            )
        ]
        k = [
            SearchResult(
                1, "a", 0.6, "keyword",
                importance_score=0.55, created_at="2026-02-02T00:00:00",
            )
        ]
        merged = hs._merge_results(v, k, 0.6, 0.4)
        m = merged[0]
        assert m.source == "hybrid"
        assert m.importance_score == pytest.approx(0.55)  # vector 缺失 → 从 keyword 补齐
        assert m.created_at == "2026-02-02T00:00:00"

    @pytest.mark.asyncio
    async def test_router_search_memories_carries_fields(self):
        """MemoryRouter._search_memories 混合分支不得丢弃评分字段
        （否则 calculate_time_score 以 now 兜底，时间通道退化）。"""
        class _HS:
            async def search(self, options):
                return [
                    SearchResult(
                        42, "内容", 0.9, "hybrid",
                        importance_score=0.66,
                        created_at="2026-03-03T08:00:00",
                        reactivation_count=5,
                    )
                ]

        from server.core.memory.router import MemoryRouter, RoutingConfig

        class _MM:
            def search_memories(self, **kw):  # pragma: no cover - 不应走到该分支
                raise AssertionError("hybrid 分支启用时不应回退 sqlite 直查")

        router = MemoryRouter(_MM(), None, None, RoutingConfig(max_memories=10, min_score_threshold=0.1))
        router.hybrid_search = _HS()
        memories = await router._search_memories("q", {})
        m = memories[0]
        assert m["importance_score"] == pytest.approx(0.66)
        assert m["created_at"] == "2026-03-03T08:00:00"
        assert m["reactivation_count"] == 5


class TestBlankVectorGuard:
    """H14: 空/零查询嵌入跳过向量通道并告警，不得进入相似度检索。"""

    @pytest.mark.asyncio
    async def test_empty_embedding_skips_vector_channel(self, hs):
        class _ZeroEmbedding:
            calls = 0

            async def get_embedding(self, query):
                self.calls += 1
                return []  # 嵌入服务失败

        store = FakeVectorStore(results=[{"memory_id": 1, "content": "c", "score": 0.99}])
        emb = _ZeroEmbedding()
        hs.vector_store = store
        hs.embedding_model = emb
        hs.sqlite_manager = FakeSQLite(
            results=[{"id": 1, "content": "c", "type": "long_term"}]
        )
        opts = HybridSearchOptions(query="q", use_vector=True, use_keyword=True)
        results = await hs.search(opts)
        # 向量通道被跳过（未调用 search_similar），结果来自 keyword 通道
        assert store.calls == []
        assert all(r.source in ("keyword", "hybrid") for r in results)
        assert emb.calls == 1

    @pytest.mark.asyncio
    async def test_zero_embedding_skips_vector_channel(self, hs):
        store = FakeVectorStore(results=[{"memory_id": 1, "content": "c", "score": 0.99}])
        hs.vector_store = store

        class _AllZero:
            async def get_embedding(self, query):
                return [0.0, 0.0, 0.0]

        hs.embedding_model = _AllZero()
        opts = HybridSearchOptions(query="q", use_vector=True, use_keyword=False)
        results = await hs.search(opts)
        assert store.calls == []
        assert results == []