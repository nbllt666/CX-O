"""CX-O-Dream 素材采集（server/autonomy/dream/collector.py）。

只读采集，不持有主库写锁、不写主库（spec "素材采集（只读）"）：
- 近 material_window_days（默认 7）天内 importance_score < 0.5 的边缘记忆
  （上限 max_material_items，按 importance_score 升序取最边缘，同分按 created_at DESC）
- 知识图谱孤立节点（度数 == 1 的实体；graph_repo 为 None / 无 list / 查询抛异常 →
  优雅降级为空列表，不阻断采集）
- 最近日记（tags 含 日记 或 #日记）的 emotion_score 作为情绪基调（无则 0.0）

任一子采集失败仅影响该部分（告警日志 + 空值），不阻断整次采集。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

from server.autonomy.dream.config import DreamConfig

logger = logging.getLogger(__name__)

# 边缘记忆阈值：importance_score < 0.5 视为正在衰减的碎片素材
_EDGE_IMPORTANCE_THRESHOLD = 0.5

# 日记标签（兼容 '日记' 与 '#日记' 两种存储形式）
_DIARY_TAGS = ("日记", "#日记")

# 图谱节点枚举上限（NodeManager.list 的 limit）
_GRAPH_NODE_LIMIT = 1000


@dataclass
class DreamMaterialSnapshot:
    """梦境素材快照（只读）。"""

    memories: List[Dict]
    isolated_entities: List[str]
    emotion_baseline: float
    agent_id: str


class DreamMaterialCollector:
    """梦境素材采集器。

    只读：仅调用 memory_manager / graph_repo 的查询方法，绝不写入主库。
    """

    def __init__(self, memory_manager, graph_repo=None, config=None):
        self._memory_manager = memory_manager
        self._graph_repo = graph_repo
        self._config = config or DreamConfig()

    async def collect(self, agent_id: str = "default") -> DreamMaterialSnapshot:
        """采集一份梦境素材快照。

        Args:
            agent_id: Agent ID，用于隔离不同 Agent 的素材

        Returns:
            DreamMaterialSnapshot：边缘记忆摘要 + 图谱孤立节点 + 情绪基调
        """
        memories = await self._collect_edge_memories(agent_id)
        isolated = await self._collect_isolated_entities(agent_id)
        emotion_baseline = await self._collect_emotion_baseline(agent_id)
        return DreamMaterialSnapshot(
            memories=memories,
            isolated_entities=isolated,
            emotion_baseline=emotion_baseline,
            agent_id=agent_id,
        )

    # ------------------------------------------------------------- 边缘记忆
    async def _collect_edge_memories(self, agent_id: str) -> List[Dict]:
        window_days = max(int(self._config.material_window_days), 0)
        max_items = max(int(self._config.max_material_items), 0)
        if max_items <= 0:
            return []
        cutoff = datetime.now() - timedelta(days=window_days)
        # 拉取候选池（大于上限留过滤余量）；仅只读查询，不做任何写入
        pool_limit = max(max_items * 5, 50)
        try:
            pool = await self._memory_manager.search_memories_async(
                query=None,
                limit=pool_limit,
                include_deleted=False,
                agent_id=agent_id,
            )
        except Exception as e:
            logger.warning(f"梦境素材采集：记忆查询失败，降级为空列表: {e}")
            return []

        edges = []
        for mem in pool or []:
            if not self._is_within_window(mem, cutoff):
                continue
            if (mem.get("importance_score") or 0.0) >= _EDGE_IMPORTANCE_THRESHOLD:
                continue
            edges.append(mem)
        # 最边缘优先：importance_score 升序，同分按 created_at 降序
        edges.sort(key=lambda m: (m.get("importance_score") or 0.0, -self._created_ts(m)))
        return edges[:max_items]

    @staticmethod
    def _is_within_window(mem: Dict, cutoff: datetime) -> bool:
        created = mem.get("created_at")
        if not created:
            return True  # 无创建时间视为窗口内（不丢素材）
        try:
            return datetime.fromisoformat(str(created)) >= cutoff
        except (ValueError, TypeError):
            return True

    @staticmethod
    def _created_ts(mem: Dict) -> float:
        created = mem.get("created_at")
        if not created:
            return 0.0
        try:
            return datetime.fromisoformat(str(created)).timestamp()
        except (ValueError, TypeError):
            return 0.0

    # ------------------------------------------------------------- 图谱孤立节点
    async def _collect_isolated_entities(self, agent_id: str) -> List[str]:
        if self._graph_repo is None:
            return []
        try:
            nodes = await self._list_graph_nodes(agent_id)
            if not nodes:
                return []
            isolated = []
            for node in nodes:
                node_id = self._graph_node_id(node)
                if not node_id:
                    continue
                neighbors = await self._graph_neighbors(node_id, agent_id)
                if len(neighbors) == 1:
                    name = self._graph_node_name(node)
                    if name:
                        isolated.append(name)
            return isolated
        except Exception as e:
            logger.warning(f"梦境素材采集：图谱孤立节点查询失败，降级为空列表: {e}")
            return []

    async def _list_graph_nodes(self, agent_id: str) -> List[Any]:
        if not hasattr(self._graph_repo, "list"):
            logger.warning("梦境素材采集：graph_repo 无 list 方法，图谱部分降级为空")
            return []
        result = self._graph_repo.list(limit=_GRAPH_NODE_LIMIT, offset=0, agent_id=agent_id)
        if inspect.isawaitable(result):
            result = await result
        if result is None:
            return []
        if isinstance(result, list):
            return result
        # SearchResult 风格：含 .items
        items = getattr(result, "items", None)
        return list(items) if isinstance(items, list) else []

    async def _graph_neighbors(self, node_id: str, agent_id: str) -> List[str]:
        if not hasattr(self._graph_repo, "get_neighbor_ids"):
            raise RuntimeError("graph_repo 无 get_neighbor_ids 方法")
        result = self._graph_repo.get_neighbor_ids(node_id, agent_id=agent_id)
        if inspect.isawaitable(result):
            result = await result
        return list(result or [])

    @staticmethod
    def _graph_node_id(node: Any) -> str:
        if isinstance(node, dict):
            return node.get("id") or ""
        return getattr(node, "id", "") or ""

    @staticmethod
    def _graph_node_name(node: Any) -> str:
        if isinstance(node, dict):
            return node.get("text_content") or node.get("name") or node.get("id") or ""
        return (
            getattr(node, "text_content", None)
            or getattr(node, "name", None)
            or getattr(node, "id", "")
            or ""
        )

    # ------------------------------------------------------------- 日记情绪基调
    async def _collect_emotion_baseline(self, agent_id: str) -> float:
        try:
            diaries = []
            for tag in _DIARY_TAGS:
                rows = await asyncio.to_thread(
                    self._memory_manager.search_by_tag, tag, "default", 100
                )
                diaries.extend(rows or [])
            # 去重（按 id）并仅保留日记记忆
            seen = set()
            unique = []
            for mem in diaries:
                if not self._is_diary(mem):
                    continue
                mid = mem.get("id")
                if mid is not None and mid in seen:
                    continue
                seen.add(mid)
                unique.append(mem)
            if not unique:
                return 0.0
            unique.sort(key=lambda m: self._created_ts(m), reverse=True)
            return float(unique[0].get("emotion_score") or 0.0)
        except Exception as e:
            logger.warning(f"梦境素材采集：日记情绪基线读取失败，降级为 0.0: {e}")
            return 0.0

    @staticmethod
    def _is_diary(mem: Dict) -> bool:
        tags = mem.get("tags") or []
        return any(str(t).lstrip("#") == "日记" for t in tags)
