"""server/autonomy/dream/collector.py（DreamMaterialCollector 素材采集）单测。

覆盖：
1. collect 返回 DreamMaterialSnapshot 全字段
2. 边缘记忆过滤：importance_score < 0.5、窗口过滤、上限截断、最边缘优先（同分按 created_at DESC）
3. 图谱孤立节点（度数 == 1）采集
4. 图谱降级：graph_repo=None / 无 list / 查询抛异常 → isolated_entities=[]
5. 日记情绪基线（tags 含 日记 / #日记，取最近），无日记 → 0.0
6. 只读：仅调用查询方法，不调用任何写方法

运行：python -m pytest tests/test_dream_collector.py -q
"""
import asyncio
from datetime import datetime, timedelta

from server.autonomy.dream.collector import (
    DreamMaterialCollector,
    DreamMaterialSnapshot,
)
from server.autonomy.dream.config import DreamConfig


def _memory(mid, content, importance_score, created_at, emotion_score=0.0, tags=None):
    """构造一条记忆字典（对齐 _row_to_memory 输出字段）。"""
    return {
        "id": mid,
        "content": content,
        "importance_score": importance_score,
        "created_at": created_at,
        "emotion_score": emotion_score,
        "tags": tags or [],
        "type": "long_term",
    }


def _iso(days_ago=0):
    return (datetime.now() - timedelta(days=days_ago)).isoformat()


class FakeMemoryManager:
    """mock memory_manager：仅实现采集用到的只读查询方法，并记录调用。

    peak_result / peak_error 用于 collect_recent_emotion_peak 用例：
    - peak_result 非 None 时 get_emotion_peak_since 返回该值
    - peak_error 非 None 时 get_emotion_peak_since 抛该异常
    """

    def __init__(self, pool=None, diary=None, peak_result=None, peak_error=None):
        self.pool = pool or []
        self.diary = diary or []
        self.called = []
        self.peak_result = peak_result
        self.peak_error = peak_error
        self.peak_calls = []

    async def search_memories_async(
        self,
        query=None,
        memory_type=None,
        tags=None,
        time_range=None,
        limit=10,
        offset=0,
        include_deleted=False,
        workspace_id="default",
        agent_id="default",
    ):
        self.called.append("search_memories_async")
        return list(self.pool)

    def search_by_tag(self, tag, workspace_id="default", limit=50):
        self.called.append(f"search_by_tag:{tag}")
        return [m for m in self.diary if tag in (m.get("tags") or [])]

    def get_emotion_peak_since(self, since_iso, workspace_id="default"):
        self.peak_calls.append((since_iso, workspace_id))
        if self.peak_error is not None:
            raise self.peak_error
        return self.peak_result


class _SearchResult:
    def __init__(self, items):
        self.items = items


class FakeGraphRepo:
    """mock graph_repo：NodeManager 风格 list + BaseGraphRepository 风格 get_neighbor_ids。"""

    def __init__(self, nodes=None, neighbor_map=None, raise_on_list=False):
        self.nodes = nodes or []
        self.neighbor_map = neighbor_map or {}
        self.raise_on_list = raise_on_list

    def list(self, limit=100, offset=0, agent_id="default"):
        if self.raise_on_list:
            raise RuntimeError("graph down")
        return _SearchResult(list(self.nodes))

    def get_neighbor_ids(self, node_id, direction="both", agent_id="default"):
        if self.raise_on_list:
            raise RuntimeError("graph down")
        return list(self.neighbor_map.get(node_id, []))


# ================================================================ 快照基本形态
class TestSnapshotShape:
    def test_returns_snapshot_fields(self):
        mm = FakeMemoryManager(pool=[_memory(1, "a", 0.2, _iso(1))])
        gr = FakeGraphRepo(
            nodes=[{"id": "n1", "text_content": "海边"}],
            neighbor_map={"n1": ["n2"]},
        )
        snap = asyncio.run(DreamMaterialCollector(mm, graph_repo=gr).collect("default"))
        assert isinstance(snap, DreamMaterialSnapshot)
        assert snap.agent_id == "default"
        assert isinstance(snap.memories, list)
        assert isinstance(snap.isolated_entities, list)
        assert isinstance(snap.emotion_baseline, float)

    def test_collect_is_read_only(self):
        mm = FakeMemoryManager(pool=[_memory(1, "a", 0.2, _iso(1))])
        snap = asyncio.run(DreamMaterialCollector(mm).collect())
        assert snap.memories
        # 只调用了查询方法，未调用任何写方法
        assert all(not c.startswith("write") and "delete" not in c for c in mm.called)


# ================================================================ 边缘记忆
class TestEdgeMemories:
    def test_edge_memories_filtered_sorted_capped(self):
        now = datetime.now()
        pool = [
            _memory(1, "a", 0.4, (now - timedelta(days=1)).isoformat()),
            _memory(2, "b", 0.6, (now - timedelta(days=1)).isoformat()),  # 太重要，排除
            _memory(3, "c", 0.2, (now - timedelta(days=10)).isoformat()),  # 超出 7 天窗口，排除
            _memory(4, "d", 0.1, (now - timedelta(days=2)).isoformat()),
            _memory(5, "e", 0.3, (now - timedelta(days=3)).isoformat()),
        ]
        cfg = DreamConfig(material_window_days=7, max_material_items=2)
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(pool=pool), config=cfg).collect())
        # 窗口内 <0.5 的为 1/4/5；上限 2；按 importance_score 升序 → [4(0.1), 5(0.3)]
        assert [m["id"] for m in snap.memories] == [4, 5]

    def test_same_importance_created_desc(self):
        now = datetime.now()
        pool = [
            _memory(1, "old", 0.2, (now - timedelta(days=5)).isoformat()),
            _memory(2, "new", 0.2, (now - timedelta(days=1)).isoformat()),
        ]
        cfg = DreamConfig(material_window_days=7, max_material_items=10)
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(pool=pool), config=cfg).collect())
        # 同 importance 时按 created_at DESC → 更近的在前
        assert [m["id"] for m in snap.memories] == [2, 1]

    def test_edge_threshold_boundary_excluded(self):
        # importance_score == 0.5 不属于边缘（<0.5），排除
        pool = [
            _memory(1, "a", 0.49, _iso(1)),
            _memory(2, "b", 0.50, _iso(1)),
            _memory(3, "c", 0.51, _iso(1)),
        ]
        cfg = DreamConfig(max_material_items=10)
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(pool=pool), config=cfg).collect())
        assert [m["id"] for m in snap.memories] == [1]

    def test_zero_max_items_returns_empty(self):
        cfg = DreamConfig(max_material_items=0)
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(pool=[_memory(1, "a", 0.2, _iso(1))]), config=cfg).collect())
        assert snap.memories == []

    def test_memory_query_error_degrades(self):
        class ErrorMM:
            async def search_memories_async(self, **kwargs):
                raise RuntimeError("db down")

        snap = asyncio.run(DreamMaterialCollector(ErrorMM()).collect())
        assert snap.memories == []


# ================================================================ 图谱孤立节点
class TestIsolatedEntities:
    def test_degree_one_entities_collected(self):
        nodes = [
            {"id": "n1", "text_content": "海边"},
            {"id": "n2", "text_content": "石头"},
            {"id": "n3", "text_content": "森林"},
        ]
        neighbor_map = {
            "n1": ["n2"],
            "n2": ["n1", "n3"],
            "n3": ["n2"],
        }
        gr = FakeGraphRepo(nodes=nodes, neighbor_map=neighbor_map)
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(), graph_repo=gr).collect())
        # n1 与 n3 度数为 1 → 孤立；n2 度数为 2 → 排除
        assert set(snap.isolated_entities) == {"海边", "森林"}

    def test_graph_none_degrades(self):
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager()).collect())
        assert snap.isolated_entities == []

    def test_graph_exception_degrades(self):
        gr = FakeGraphRepo(raise_on_list=True)
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(), graph_repo=gr).collect())
        assert snap.isolated_entities == []

    def test_graph_without_list_degrades(self):
        class NoListRepo:
            def get_neighbor_ids(self, node_id, agent_id="default"):
                return ["x"]

        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(), graph_repo=NoListRepo()).collect())
        assert snap.isolated_entities == []

    def test_graph_node_missing_neighbor_api_degrades(self):
        class NoNeighborRepo:
            def list(self, limit=100, offset=0, agent_id="default"):
                return _SearchResult([{"id": "n1", "text_content": "海边"}])

        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager(), graph_repo=NoNeighborRepo()).collect())
        assert snap.isolated_entities == []


# ================================================================ 日记情绪基调
class TestEmotionBaseline:
    def test_baseline_from_most_recent_diary(self):
        mm = FakeMemoryManager(
            diary=[
                _memory(1, "日记一", 0.4, _iso(2), emotion_score=-0.5, tags=["日记"]),
                _memory(2, "日记二", 0.4, _iso(1), emotion_score=0.8, tags=["#日记"]),
            ]
        )
        snap = asyncio.run(DreamMaterialCollector(mm).collect())
        # 取最近日记的 emotion_score
        assert snap.emotion_baseline == 0.8

    def test_baseline_zero_when_no_diary(self):
        snap = asyncio.run(DreamMaterialCollector(FakeMemoryManager()).collect())
        assert snap.emotion_baseline == 0.0

    def test_baseline_zero_when_diary_without_emotion(self):
        mm = FakeMemoryManager(diary=[_memory(1, "无情绪", 0.4, _iso(1), emotion_score=0.0, tags=["日记"])])
        snap = asyncio.run(DreamMaterialCollector(mm).collect())
        assert snap.emotion_baseline == 0.0

    def test_diary_query_error_degrades_to_zero(self):
        class ErrorMM:
            async def search_memories_async(self, **kwargs):
                return []

            def search_by_tag(self, tag, workspace_id="default", limit=50):
                raise RuntimeError("db down")

        snap = asyncio.run(DreamMaterialCollector(ErrorMM()).collect())
        assert snap.emotion_baseline == 0.0


# ================================================================ 最近事件情绪峰值
class TestRecentEmotionPeak:
    def test_peak_passthrough(self):
        mm = FakeMemoryManager(peak_result={"peak": 0.85, "count": 3})
        result = asyncio.run(DreamMaterialCollector(mm).collect_recent_emotion_peak("default"))
        assert result == {"peak": 0.85, "count": 3}

    def test_window_and_workspace_args(self):
        mm = FakeMemoryManager(peak_result={"peak": 0.5, "count": 1})
        before = datetime.now()
        asyncio.run(
            DreamMaterialCollector(mm).collect_recent_emotion_peak("default", window_hours=6)
        )
        after = datetime.now()
        # 只调用一次 get_emotion_peak_since，workspace_id 硬编码 "default"
        assert len(mm.peak_calls) == 1
        since_iso, workspace_id = mm.peak_calls[0]
        assert workspace_id == "default"
        # 宽松断言：since_iso 约为 now - 6h（落在测试执行的时间窗口内）
        since = datetime.fromisoformat(since_iso)
        assert before - timedelta(hours=6) <= since <= after - timedelta(hours=6)

    def test_exception_degrades_without_raise(self):
        mm = FakeMemoryManager(peak_error=RuntimeError("db down"))
        result = asyncio.run(DreamMaterialCollector(mm).collect_recent_emotion_peak("default"))
        assert result == {"peak": 0.0, "count": 0}

    def test_none_result_degrades(self):
        mm = FakeMemoryManager(peak_result=None)
        result = asyncio.run(DreamMaterialCollector(mm).collect_recent_emotion_peak("default"))
        assert result == {"peak": 0.0, "count": 0}

    def test_non_dict_result_degrades(self):
        mm = FakeMemoryManager(peak_result=[0.9, 5])
        result = asyncio.run(DreamMaterialCollector(mm).collect_recent_emotion_peak("default"))
        assert result == {"peak": 0.0, "count": 0}

    def test_dict_missing_keys_degrades(self):
        mm = FakeMemoryManager(peak_result={"peak": 0.9})
        result = asyncio.run(DreamMaterialCollector(mm).collect_recent_emotion_peak("default"))
        assert result == {"peak": 0.0, "count": 0}
