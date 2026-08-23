"""server.core.memory.router (MemoryRouter) 梦境召回隔离单元测试。

通过 FakeMemoryManager 注入隔离，覆盖梦境召回隔离（红线 R1）：
常规 chat 场景结果不含 dream、dream_recall 场景/触发词命中仅放行 confirmed 梦境、
未 confirmed 梦境不放行、梦境 relevance 降权与 source_counts 统计。

运行：python -m pytest tests/test_memory_router_dream.py -v
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


def _mem(mid, score=0.5, type="long_term", metadata=None, permanent=False, content="x"):
    return {
        "id": mid,
        "content": content,
        "score": score,
        "final_score": score,
        "permanent": permanent,
        "type": type,
        "metadata": metadata or {},
    }


def _router(manager):
    config = RoutingConfig(
        importance_weight=0.3,
        time_weight=0.3,
        relevance_weight=0.4,
        max_memories=10,
        min_score_threshold=0.3,
        high_priority_threshold=0.8,
    )
    return MemoryRouter(manager, config=config)


class TestIsDreamRecallScene:
    def test_dream_recall_scene(self):
        r = _router(FakeMemoryManager())
        assert r._is_dream_recall_scene("anything", "dream_recall") is True

    def test_chinese_trigger_words(self):
        r = _router(FakeMemoryManager())
        assert r._is_dream_recall_scene("昨晚梦见了什么", "chat") is True
        assert r._is_dream_recall_scene("说说梦到的事", "chat") is True
        assert r._is_dream_recall_scene("关于梦", "chat") is True

    def test_english_case_insensitive(self):
        r = _router(FakeMemoryManager())
        assert r._is_dream_recall_scene("Tell me about your DREAM", "chat") is True
        assert r._is_dream_recall_scene("Dreams of home", "chat") is True

    def test_no_trigger(self):
        r = _router(FakeMemoryManager())
        assert r._is_dream_recall_scene("今天天气如何", "chat") is False
        assert r._is_dream_recall_scene(None, "chat") is False
        assert r._is_dream_recall_scene("", "chat") is False


class TestApplyDreamFilter:
    def test_chat_excludes_dreams(self):
        r = _router(FakeMemoryManager())
        mems = [
            _mem(1, type="long_term"),
            _mem(2, type="dream", metadata={"consolidation_state": "confirmed"}),
            _mem(3, type="dream", metadata={"consolidation_state": "pending"}),
        ]
        filtered = r._apply_dream_filter(mems, "hello", "chat")
        assert [m["id"] for m in filtered] == [1]

    def test_dream_recall_allows_only_confirmed(self):
        r = _router(FakeMemoryManager())
        mems = [
            _mem(1, type="dream", metadata={"consolidation_state": "confirmed"}),
            _mem(2, type="dream", metadata={"consolidation_state": "pending"}),
            _mem(3, type="dream", metadata={"consolidation_state": "surfaced"}),
            _mem(4, type="dream", metadata={}),
            _mem(5, type="long_term"),
        ]
        filtered = r._apply_dream_filter(mems, "x", "dream_recall")
        assert [m["id"] for m in filtered] == [1, 5]

    def test_trigger_word_allows_only_confirmed(self):
        r = _router(FakeMemoryManager())
        mems = [
            _mem(1, type="dream", metadata={"consolidation_state": "confirmed"}),
            _mem(2, type="dream", metadata={"consolidation_state": "pending"}),
        ]
        filtered = r._apply_dream_filter(mems, "昨晚的梦", "chat")
        assert [m["id"] for m in filtered] == [1]

    def test_metadata_type_dream_detected(self):
        # 混合检索路径 type 可能在 metadata 中
        r = _router(FakeMemoryManager())
        mems = [
            _mem(1, type="long_term", metadata={"type": "dream", "consolidation_state": "confirmed"}),
        ]
        filtered = r._apply_dream_filter(mems, "hello", "chat")
        assert filtered == []


class TestScoringDream:
    def test_dream_relevance_downweighted(self):
        r = _router(FakeMemoryManager())
        scored = r._score_memories(
            [_mem(1, score=0.8, type="dream")],
            "q",
            {"importance": 0.3, "time": 0.3, "relevance": 0.4},
            {},
        )
        assert scored[0]["component_scores"]["relevance"] == pytest.approx(0.8 * 0.7)

    def test_non_dream_relevance_not_downweighted(self):
        r = _router(FakeMemoryManager())
        scored = r._score_memories(
            [_mem(1, score=0.8, type="long_term")],
            "q",
            {"importance": 0.3, "time": 0.3, "relevance": 0.4},
            {},
        )
        assert scored[0]["component_scores"]["relevance"] == pytest.approx(0.8)


class TestRouteDreamIsolation:
    @pytest.mark.asyncio
    async def test_chat_route_excludes_dreams(self):
        manager = FakeMemoryManager(
            [
                _mem(1, score=0.6, type="long_term"),
                _mem(2, score=0.6, type="dream", metadata={"consolidation_state": "confirmed"}),
                _mem(3, score=0.6, type="dream", metadata={"consolidation_state": "pending"}),
            ]
        )
        result = await _router(manager).route("你好", scene_type="chat")
        assert all(m.get("type") != "dream" for m in result.memories)

    @pytest.mark.asyncio
    async def test_dream_recall_route_allows_confirmed(self):
        manager = FakeMemoryManager(
            [
                _mem(1, score=0.5, type="dream", metadata={"consolidation_state": "confirmed"}),
                _mem(2, score=0.6, type="long_term"),
            ]
        )
        result = await _router(manager).route("回忆", scene_type="dream_recall")
        assert any(m.get("id") == 1 for m in result.memories)
        assert any(m.get("type") == "dream" for m in result.memories)

    @pytest.mark.asyncio
    async def test_trigger_route_allows_confirmed(self):
        manager = FakeMemoryManager(
            [
                _mem(1, score=0.5, type="dream", metadata={"consolidation_state": "confirmed"}),
            ]
        )
        result = await _router(manager).route("昨晚梦到了什么", scene_type="chat")
        assert any(m.get("id") == 1 for m in result.memories)

    @pytest.mark.asyncio
    async def test_english_trigger_route_allows_confirmed(self):
        manager = FakeMemoryManager(
            [
                _mem(1, score=0.5, type="dream", metadata={"consolidation_state": "confirmed"}),
            ]
        )
        result = await _router(manager).route("Tell me about a DREAM I had", scene_type="chat")
        assert any(m.get("id") == 1 for m in result.memories)

    @pytest.mark.asyncio
    async def test_unconfirmed_dream_excluded_even_in_dream_recall(self):
        manager = FakeMemoryManager(
            [
                _mem(1, score=0.6, type="dream", metadata={"consolidation_state": "pending"}),
                _mem(2, score=0.6, type="dream", metadata={"consolidation_state": "surfaced"}),
            ]
        )
        result = await _router(manager).route("回忆", scene_type="dream_recall")
        assert result.memories == []

    @pytest.mark.asyncio
    async def test_source_counts_includes_dream(self):
        manager = FakeMemoryManager(
            [
                _mem(1, score=0.5, type="dream", metadata={"consolidation_state": "confirmed"}),
                _mem(2, score=0.6, type="long_term"),
            ]
        )
        result = await _router(manager).route("回忆", scene_type="dream_recall")
        assert result.source_counts["dream"] == 1

    @pytest.mark.asyncio
    async def test_route_returns_routing_result(self):
        result = await _router(FakeMemoryManager([_mem(1, score=0.6)])).route("hi")
        assert isinstance(result, RoutingResult)
        assert "dream" in result.source_counts
