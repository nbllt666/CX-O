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
        # 差异修复：_get_recent_memories 按 tags 过滤会话（真实记忆把会话 id 记于
        # tags），旧 fake 只给 session_id 无 tags → test_filters_by_session_id 恒空。
        "tags": [session_id] if session_id else [],
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
        """上界 clamp 语义（归一化乘法门控）：三项全满时 final==1.0。

        改造说明：原断言在 weights 全 1.0、score=0.9 时期望 final==1.0，依据的是
        旧线性加权和（0.6+0.6+0.9=2.1 被 clamp 到 1.0）。新公式
        `final = relevance × (w_i·importance + w_t·time) / (w_i+w_t)` 下，该输入的
        实际值仅为 0.54（见 test_score_normalized_gate_for_default_candidate），
        故此处改用"三项全满"的明确上界用例。
        """
        mem = _mem(1, score=1.0, permanent=True)  # permanent → time_score 恒 1.0
        mem["importance_score"] = 1.0
        scored = router._score_memories(
            [mem], "q", {"importance": 1.0, "time": 1.0, "relevance": 1.0}, {}
        )
        assert scored[0]["final_score"] == pytest.approx(1.0)

    def test_score_normalized_gate_for_default_candidate(self, router):
        """归一化乘法门控核算：score=0.9、importance/time 取缺省 0.6 → final=0.54。

        旧加权和在 weights 全 1.0 下得 2.1（clamp 到 1.0）；新公式以 (w_i+w_t)
        归一，三项不再线性相加，故该输入实际值为 0.9×(0.6·1+0.6·1)/2=0.54。
        """
        scored = router._score_memories(
            [_mem(1, score=0.9)], "q", {"importance": 1.0, "time": 1.0, "relevance": 1.0}, {}
        )
        assert scored[0]["final_score"] == pytest.approx(0.54)


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


# ==================================================================
# T3 新增：归一化乘法门控 / recent 并入去重 / 真实相关性 / 异常兜底
# ==================================================================


class FakeChannelMemoryManager:
    """区分 recent（tags 查询）与检索（query）两条通道的假管理器。

    - 带 tags 的调用 = `_get_recent_memories` 的会话标签分页查询；
    - 无 tags 的调用 = `_search_memories` 的 hybrid 不可用回退直查。
    以 **kw 原样记录调用参数，便于断言 agent_id 是否下传。
    """

    def __init__(self, recent=None, search=None):
        self.recent = recent or []
        self.search = search or []
        self.calls = []

    def search_memories(self, **kw):
        self.calls.append(dict(kw))
        if kw.get("tags"):
            return list(self.recent) if kw.get("offset", 0) == 0 else []
        return list(self.search)


class FakeEmbeddingModel:
    """可预测向量的假嵌入模型：query 与候选文本向量均显式给定。"""

    def __init__(self, query_vec=None, text_vecs=None, fail=False):
        self.query_vec = query_vec
        self.text_vecs = text_vecs
        self.fail = fail
        self.get_embedding_calls = 0
        self.get_embeddings_calls = 0

    async def get_embedding(self, query):
        self.get_embedding_calls += 1
        return list(self.query_vec or [])

    async def get_embeddings(self, texts):
        self.get_embeddings_calls += 1
        if self.fail:
            return []
        return [list(v) for v in (self.text_vecs or [])]


class TestMultiplicativeGate:
    """零相关淘汰 / 弱相关不可补偿 / 上界 clamp（归一化乘法门控）。"""

    def test_zero_relevance_cannot_be_compensated(self, router):
        """relevance=0（importance/time 拉满）→ final=0，维度间不可补偿。"""
        mem = _mem(1, score=0.0)
        mem["importance_score"] = 1.0  # time 因 importance>=0.95 亦为 1.0
        scored = router._score_memories(
            [mem], "q", {"importance": 0.45, "time": 0.20, "relevance": 0.35}, {}
        )
        assert scored[0]["component_scores"]["importance"] == pytest.approx(1.0)
        assert scored[0]["component_scores"]["time"] == pytest.approx(1.0)
        assert scored[0]["final_score"] == 0.0

    def test_weak_relevance_cannot_exceed_its_relevance(self, router):
        """chat 权重下 relevance=0.10、importance/time 拉满 → final=0.10（上界即 relevance）。"""
        chat_weights = {"importance": 0.45, "time": 0.20, "relevance": 0.35}
        mem = _mem(1, score=0.10)
        mem["importance_score"] = 1.0
        scored = router._score_memories([mem], "q", chat_weights, {})
        assert scored[0]["final_score"] == pytest.approx(0.10)
        # 0.10 < min_score_threshold=0.15 → 被过滤
        weak_router = MemoryRouter(
            FakeMemoryManager(), config=RoutingConfig(max_memories=10, min_score_threshold=0.15)
        )
        assert weak_router._apply_filters(scored) == []

    def test_gate_upper_bound_and_saturation(self, router):
        """三项全满 → 1.0；仅 importance/time 半满 → 0.5（归一化分母的饱和度）。"""
        full = _mem(1, score=1.0, permanent=True)
        full["importance_score"] = 1.0
        half = _mem(2, score=1.0)
        half["importance_score"] = 0.5  # time≈0.5（非 permanent，importance<0.95）
        weights = {"importance": 0.45, "time": 0.20, "relevance": 0.35}
        scored = router._score_memories([full, half], "q", weights, {})
        by_id = {m["id"]: m["final_score"] for m in scored}
        assert by_id[1] == pytest.approx(1.0)
        assert by_id[2] == pytest.approx(0.5, abs=0.01)


class TestZeroRelevanceEndToEnd:
    """零相关候选经 `_apply_filters` 端到端被淘汰。"""

    def test_zero_relevance_filtered_end_to_end(self, router):
        mem = _mem(1, score=0.0)  # 非 permanent、非 explicitly_mentioned
        mem["importance_score"] = 1.0
        scored = router._score_memories(
            [mem], "q", {"importance": 0.45, "time": 0.20, "relevance": 0.35}, {}
        )
        assert scored[0]["final_score"] == 0.0
        assert router._apply_filters(scored) == []


class TestMergeCandidates:
    """`_merge_candidates` 按 id 去重 + recent 字段补齐。"""

    def test_dedup_keeps_search_score(self, router):
        recent = [{"id": 1, "content": "会话行", "tags": ["s1"], "type": "long_term"}]
        search = [{"id": 1, "content": "检索行", "score": 0.9, "source": "vector"}]
        merged = router._merge_candidates(recent, search)
        assert len(merged) == 1
        assert merged[0]["score"] == pytest.approx(0.9)  # 保留检索真实分数
        assert merged[0]["content"] == "检索行"

    def test_dedup_fills_fields_from_recent(self, router):
        recent = [
            {"id": 7, "content": "会话行", "tags": ["s1"], "permanent": True, "type": "long_term"}
        ]
        search = [{"id": 7, "content": "检索行", "score": 0.8, "source": "vector"}]
        merged = router._merge_candidates(recent, search)
        assert len(merged) == 1
        assert merged[0]["permanent"] is True  # 检索形态缺失 → recent 补齐
        assert merged[0]["type"] == "long_term"
        assert merged[0]["tags"] == ["s1"]
        # `_apply_filters` 的 permanent 放行对同 id 候选可见
        assert len(router._apply_filters([{**merged[0], "final_score": 0.0}])) == 1

    def test_recent_only_candidate_appended(self, router):
        recent = [{"id": 9, "content": "仅会话", "tags": ["s1"]}]
        search = [{"id": 8, "content": "检索", "score": 0.9}]
        merged = router._merge_candidates(recent, search)
        assert [m["id"] for m in merged] == [8, 9]  # 检索在前、recent 独有项在后


class TestRecentChannelRoute:
    """route() 中 recent 通道并入与 agent_id 下传。"""

    @pytest.mark.asyncio
    async def test_route_includes_recent_only_candidate(self):
        recent = [
            {"id": 201, "content": "会话摘要", "type": "long_term", "tags": ["s1"], "permanent": False}
        ]
        search = [{"id": 101, "content": "检索记忆", "score": 0.9, "type": "long_term"}]
        mm = FakeChannelMemoryManager(recent=recent, search=search)
        router = MemoryRouter(
            mm, config=RoutingConfig(max_memories=10, min_score_threshold=0.2)
        )
        result = await router.route("q", session_id="s1")
        ids = [m["id"] for m in result.memories]
        assert 201 in ids  # recent 独有候选进入最终结果
        assert 101 in ids
        assert "最近交互记忆优先" in result.applied_rules

    @pytest.mark.asyncio
    async def test_route_passes_agent_id_to_recent_channel(self):
        mm = FakeChannelMemoryManager()
        router = MemoryRouter(
            mm, config=RoutingConfig(max_memories=10, min_score_threshold=0.2)
        )
        await router.route("q", session_id="s1", agent_id="agent-x")
        recent_calls = [c for c in mm.calls if c.get("tags")]
        assert recent_calls
        assert recent_calls[0].get("agent_id") == "agent-x"

    @pytest.mark.asyncio
    async def test_route_omits_agent_id_when_none(self):
        mm = FakeChannelMemoryManager()
        router = MemoryRouter(
            mm, config=RoutingConfig(max_memories=10, min_score_threshold=0.2)
        )
        await router.route("q", session_id="s1")
        recent_calls = [c for c in mm.calls if c.get("tags")]
        assert recent_calls
        assert "agent_id" not in recent_calls[0]  # None 时不透传（保持底层缺省语义）


class TestFillMissingRelevance:
    """`_fill_missing_relevance`：(1+cos)/2 映射、失败回退、对齐不一致整体弃用。"""

    def _router(self, emb):
        return MemoryRouter(
            FakeMemoryManager(), embedding_model=emb, config=RoutingConfig(max_memories=10)
        )

    @pytest.mark.asyncio
    async def test_fill_writes_cosine_mapping(self):
        mems = [{"id": 1, "content": "同向"}, {"id": 2, "content": "正交"}, {"id": 3, "content": "反向"}]
        emb = FakeEmbeddingModel(text_vecs=[[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]])
        router = self._router(emb)
        await router._fill_missing_relevance(mems, "q", [1.0, 0.0])
        assert mems[0]["score"] == pytest.approx(1.0)   # cos=1  → (1+1)/2
        assert mems[1]["score"] == pytest.approx(0.5)   # cos=0  → (1+0)/2
        assert mems[2]["score"] == pytest.approx(0.0)   # cos=-1 → (1-1)/2

    @pytest.mark.asyncio
    async def test_embedding_failure_keeps_default_without_raising(self):
        mems = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
        emb = FakeEmbeddingModel(fail=True)  # get_embeddings 返回空
        router = self._router(emb)
        await router._fill_missing_relevance(mems, "q", [1.0, 0.0])  # 不应抛异常
        assert all("score" not in m for m in mems)
        scored = router._score_memories(mems, "q", {"importance": 0.45, "time": 0.20}, {})
        assert all(m["component_scores"]["relevance"] == pytest.approx(0.5) for m in scored)

    @pytest.mark.asyncio
    async def test_alignment_mismatch_discards_all(self):
        mems = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
        emb = FakeEmbeddingModel(text_vecs=[[1.0, 0.0]])  # 1 != 2，整体弃用
        router = self._router(emb)
        await router._fill_missing_relevance(mems, "q", [1.0, 0.0])
        assert all("score" not in m for m in mems)  # 无一被按位置错配写入

    @pytest.mark.asyncio
    async def test_missing_score_targets_only(self):
        """已有 score 的候选不被覆盖（仅补算缺 score 的候选）。"""
        mems = [{"id": 1, "content": "有分", "score": 0.33}, {"id": 2, "content": "缺分"}]
        emb = FakeEmbeddingModel(text_vecs=[[1.0, 0.0]])
        router = self._router(emb)
        await router._fill_missing_relevance(mems, "q", [1.0, 0.0])
        assert mems[0]["score"] == pytest.approx(0.33)
        assert mems[1]["score"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_attempted_failed_skips_refill(self):
        """U5：嵌入已尝试且失败（标志为真）→ 不重复补算（get_embedding 0 次），保持缺省。"""
        mems = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
        emb = FakeEmbeddingModel(query_vec=[1.0, 0.0])
        router = self._router(emb)
        await router._fill_missing_relevance(
            mems, "q", None, embedding_attempted_failed=True
        )
        assert emb.get_embedding_calls == 0
        assert all("score" not in m for m in mems)


class TestScoringExceptionFallback:
    """N4 异常兜底分支：单条评分异常回退原始 score（缺省 0.3）且不中断整批。"""

    def test_exception_uses_raw_score_and_continues(self, router):
        def _boom(memory):
            raise RuntimeError("boom")

        router.decay_calculator.calculate_importance_score = _boom
        mems = [
            {"id": 1, "content": "a", "score": 0.77},
            {"id": 2, "content": "b", "score": 0.42},
            {"id": 3, "content": "c"},  # 无 score → 缺省 0.3
        ]
        scored = router._score_memories(mems, "q", {"importance": 0.45, "time": 0.20}, {})
        assert len(scored) == 3  # 整批未被单条异常拖垮
        assert scored[0]["final_score"] == pytest.approx(0.77)
        assert scored[1]["final_score"] == pytest.approx(0.42)
        assert scored[2]["final_score"] == pytest.approx(0.3)


class TestAttemptedEmbeddingFailureNoDoubleCall:
    """T5b: 嵌入失败路径下 route() 每请求只尝试 1 次嵌入（不重复）。

    装饰真实 HybridSearch（含 keyword 回退通道），验证 route 的失败标志
    经 options 下传后，向量通道不再重复调用嵌入服务。
    """

    @pytest.mark.asyncio
    async def test_route_embedding_failure_attempted_once(self):
        class _FailingEmbedding:
            """嵌入服务离线：get_embedding 恒返回空（H14 空白向量）。"""

            def __init__(self):
                self.calls = 0

            async def get_embedding(self, query):
                self.calls += 1
                return []

            async def get_embeddings(self, texts):
                return []

        class _Store:
            async def search_similar(self, *a, **k):  # pragma: no cover
                raise AssertionError("嵌入失败时不应进入向量检索")

        emb = _FailingEmbedding()
        router = MemoryRouter(
            FakeMemoryManager(),
            vector_store=_Store(),
            embedding_model=emb,
            config=RoutingConfig(max_memories=10, min_score_threshold=0.2),
        )
        assert router.hybrid_search is not None  # 构造时已装配真实 HybridSearch

        result = await router.route("日记", agent_id="default")

        # 修复前：_embed_query 1 次 + hybrid _vector_search 自算 1 次 = 2 次
        assert emb.calls == 1
        assert result.memories == []


class TestNoRefillEndToEndU5:
    """U5 端到端：嵌入失败 + 存在无 score 候选（recent 独有项）时，全链路仅 1 次嵌入。"""

    @pytest.mark.asyncio
    async def test_route_no_refill_with_scoreless_candidate(self):
        class _FailingEmbedding:
            def __init__(self):
                self.calls = 0

            async def get_embedding(self, query):
                self.calls += 1
                return []

            async def get_embeddings(self, texts):
                self.calls += 1
                return []

        class _Store:
            async def search_similar(self, *a, **k):  # pragma: no cover
                raise AssertionError("嵌入失败时不应进入向量检索")

        # 无 "score" 键的会话记忆（recent 通道独有项）→ _fill_missing_relevance 的 targets 非空
        mem = {"id": 201, "content": "会话上下文", "tags": ["s1"], "type": "long_term"}
        emb = _FailingEmbedding()
        router = MemoryRouter(
            FakeMemoryManager([mem]),
            vector_store=_Store(),
            embedding_model=emb,
            config=RoutingConfig(max_memories=10, min_score_threshold=0.2),
        )
        result = await router.route("日记", session_id="s1", agent_id="default")

        # 修复前：_embed_query 1 + hybrid 自算 1 + _fill_missing_relevance 补算 1 = 3 次
        assert emb.calls == 1
        # 候选仍以缺省相关性 0.5 参与打分并通过阈值（0.5 × base ≥ 0.2）
        assert any(m.get("id") == 201 for m in result.memories)


class TestFallbackAgentIsolationU6:
    """U6：hybrid 不可用回退分支按 agent_id 条件下传（None 不透传）。"""

    @pytest.mark.asyncio
    async def test_fallback_passes_agent_id_conditionally(self):
        class _RecordingManager:
            def __init__(self):
                self.kwargs = []

            def search_memories(self, **kw):
                self.kwargs.append(kw)
                return []

        mgr = _RecordingManager()
        router = MemoryRouter(mgr, config=RoutingConfig(max_memories=10))
        assert router.hybrid_search is None  # 无 vector_store/embedding_model → 走回退分支

        await router._search_memories("q", {"limit": 5, "agent_id": "agent-x"})
        assert mgr.kwargs[-1].get("agent_id") == "agent-x"

        await router._search_memories("q", {"limit": 5})
        assert "agent_id" not in mgr.kwargs[-1]