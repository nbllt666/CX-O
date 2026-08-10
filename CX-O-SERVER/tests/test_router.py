"""server.core.memory.router (MemoryRouter) 单元测试。

通过 FakeMemoryManager + FakeHybridSearch 注入隔离，覆盖路由流程的评分、
过滤、场景权重、场景调整、状态查询等核心逻辑。
运行：python -m pytest tests/test_router.py -v
"""
import pytest

from server.core.memory.router import MemoryRouter, RoutingConfig, RoutingResult


class FakeMemoryManager:
    def __init__(self, memories=None):
        self._memories = memories or []
        self.search_calls = 0

    def search_memories(self, query=None, memory_type=None, tags=None, limit=None, agent_id="default", **kw):
        self.search_calls += 1
        # 首次调用返回记忆，后续返回空以终止 _get_recent_memories 的分页循环
        if self.search_calls > 1:
            return []
        return self._memories


class FakeHybridSearch:
    def __init__(self, results=None):
        self._results = results or []
        self.last_options = None

    async def search(self, options):
        self.last_options = options
        return self._results


def _mem(mid, score=0.5, permanent=False, content="x", session_id=None):
    return {
        "id": mid,
        "content": content,
        "score": score,
        "final_score": score,
        "permanent": permanent,
        "session_id": session_id,
        "type": "long_term",
    }


@pytest.fixture
def manager():
    return FakeMemoryManager()


@pytest.fixture
def router(manager):
    config = RoutingConfig(
        importance_weight=0.3,
        time_weight=0.3,
        relevance_weight=0.4,
        max_memories=10,
        min_score_threshold=0.3,
        high_priority_threshold=0.8,
    )
    return MemoryRouter(manager, config=config)


class TestWeights:
    def test_scene_awareness_disabled(self, router):
        router.config.scene_awareness_enabled = False
        weights = router._get_weights("task")
        assert weights == {
            "importance": router.config.importance_weight,
            "time": router.config.time_weight,
            "relevance": router.config.relevance_weight,
        }

    def test_task_weights(self, router):
        weights = router._get_weights("task")
        assert weights["relevance"] == 0.5
        assert weights["importance"] == 0.30
        assert weights["time"] == 0.20

    def test_unknown_scene_falls_back_chat(self, router):
        weights = router._get_weights("nonexistent")
        assert weights["relevance"] == 0.35
        assert weights["importance"] == 0.45


class TestScoring:
    def test_score_memories_sets_final_score(self, router):
        scored = router._score_memories(
            [_mem(1, score=0.5)], "q", {"importance": 0.3, "time": 0.3, "relevance": 0.4}, {}
        )
        m = scored[0]
        assert "final_score" in m
        assert m["final_score"] <= 1.0
        assert m["component_scores"]["relevance"] == 0.5

    def test_score_clamped_to_one(self, router):
        scored = router._score_memories(
            [_mem(1, score=0.9)], "q", {"importance": 1.0, "time": 1.0, "relevance": 1.0}, {}
        )
        assert scored[0]["final_score"] == 1.0


class TestFilters:
    def test_permanent_always_included(self, router):
        filtered = router._apply_filters([_mem(1, score=0.0, permanent=True)])
        assert len(filtered) == 1

    def test_high_priority_included(self, router):
        filtered = router._apply_filters([_mem(1, score=0.85)])
        assert len(filtered) == 1

    def test_below_threshold_excluded(self, router):
        filtered = router._apply_filters([_mem(1, score=0.1)])
        assert filtered == []

    def test_explicitly_mentioned_included(self, router):
        m = _mem(1, score=0.1)
        m["explicitly_mentioned"] = True
        filtered = router._apply_filters([m])
        assert len(filtered) == 1


class TestSceneAdjustment:
    def test_task_sorts_by_relevance(self, router):
        mems = [
            {**_mem(1), "component_scores": {"relevance": 0.3}},
            {**_mem(2), "component_scores": {"relevance": 0.9}},
        ]
        adjusted = router._apply_scene_adjustment(mems, "task", {})
        assert adjusted[0]["id"] == 2

    def test_first_interaction_boosts_score(self, router):
        mems = [{**_mem(1, score=0.5), "final_score": 0.5}]
        adjusted = router._apply_scene_adjustment(mems, "first_interaction", {})
        assert adjusted[0]["final_score"] == pytest.approx(0.6, abs=0.001)

    def test_chat_no_change(self, router):
        mems = [{**_mem(1), "final_score": 0.5}]
        adjusted = router._apply_scene_adjustment(mems, "chat", {})
        assert adjusted[0]["final_score"] == 0.5


class TestRecentMemories:
    def test_no_session_id_returns_empty(self, router):
        assert router._get_recent_memories(None) == []

    def test_filters_by_session_id(self, router):
        manager = FakeMemoryManager([_mem(1, session_id="s1"), _mem(2, session_id="s2")])
        config = RoutingConfig(max_memories=10, min_score_threshold=0.3)
        r = MemoryRouter(manager, config=config)
        recent = r._get_recent_memories("s1")
        assert [m["id"] for m in recent] == [1]


class TestSearchMemories:
    @pytest.mark.asyncio
    async def test_without_hybrid_uses_manager(self, router):
        router.memory_manager._memories = [_mem(1, score=0.6)]
        results = await router._search_memories("q", {"limit": 5})
        assert results[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_with_hybrid_uses_hybrid(self, router):
        fake_hybrid = FakeHybridSearch()
        router.hybrid_search = fake_hybrid
        router.memory_manager._memories = []
        results = await router._search_memories("q", {"limit": 5})
        assert fake_hybrid.last_options is not None
        assert fake_hybrid.last_options.vector_weight == 0.6


class TestRoute:
    @pytest.mark.asyncio
    async def test_route_returns_routing_result(self, router):
        manager = FakeMemoryManager([_mem(1, score=0.6, permanent=False)])
        config = RoutingConfig(max_memories=10, min_score_threshold=0.3)
        r = MemoryRouter(manager, config=config)
        result = await r.route("query")
        assert isinstance(result, RoutingResult)
        assert result.context["query"] == "query"
        assert result.applied_weights["relevance"] > 0

    @pytest.mark.asyncio
    async def test_route_search_failure_returns_empty(self, router):
        class Boom:
            def search_memories(self, *a, **k):
                raise RuntimeError("boom")

        r = MemoryRouter(Boom(), config=RoutingConfig(max_memories=10, min_score_threshold=0.3))
        result = await r.route("q")
        # 搜索异常在 _search_memories 内部被吞掉，返回空记忆但保持正常上下文
        assert result.memories == []
        assert result.context["query"] == "q"


class TestStatus:
    def test_get_routing_status(self, router):
        status = router.get_routing_status()
        assert status["enabled"] is True
        assert status["config"]["scene_awareness_enabled"] is True
        assert "task" in status["scene_configs"]
        assert status["scene_configs"]["task"]["weights"]["relevance"] == 0.5