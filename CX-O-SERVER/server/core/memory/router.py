"""记忆路由——多源记忆检索结果的评分合并与选优决策。"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List

from server.config import Settings
from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class RoutingResult:
    """记忆路由的输出结果，封装选中的记忆列表、总分、各来源计数、实际权重与命中规则。"""
    memories: List[Dict]
    total_score: float
    source_counts: Dict[str, int]
    applied_weights: Dict[str, float]
    applied_rules: List[str]
    context: Dict = field(default_factory=dict)


@dataclass
class RoutingConfig:
    """记忆路由评分配置，定义重要性/时间/相关性权重、场景感知开关及数量与分数阈值。"""
    importance_weight: float = 0.35
    time_weight: float = 0.25
    relevance_weight: float = 0.4
    hard_rules_enabled: bool = True
    scene_awareness_enabled: bool = True
    max_memories: int = None
    min_score_threshold: float = None
    high_priority_threshold: float = 0.8


class MemoryRouter:
    """记忆路由器，聚合近端记忆与向量/关键词检索结果，按场景权重评分、过滤并选出最终记忆。"""
    SCENE_CONFIGS = {
        "task": {
            "description": "任务型对话",
            "relevance_weight": 0.5,
            "importance_weight": 0.30,
            "time_weight": 0.20,
        },
        "chat": {
            "description": "闲聊/情感对话",
            "relevance_weight": 0.35,
            "importance_weight": 0.45,
            "time_weight": 0.20,
        },
        "first_interaction": {
            "description": "首次交互",
            "relevance_weight": 0.40,
            "importance_weight": 0.30,
            "time_weight": 0.30,
        },
        "recall": {
            "description": "记忆召回",
            "relevance_weight": 0.50,
            "importance_weight": 0.25,
            "time_weight": 0.25,
        },
        "learning": {
            "description": "学习/知识获取",
            "relevance_weight": 0.45,
            "importance_weight": 0.35,
            "time_weight": 0.20,
        },
        "problem_solving": {
            "description": "问题解决",
            "relevance_weight": 0.55,
            "importance_weight": 0.25,
            "time_weight": 0.20,
        },
        "creative": {
            "description": "创造性对话",
            "relevance_weight": 0.30,
            "importance_weight": 0.30,
            "time_weight": 0.40,
        },
    }

    # 梦境召回触发词（大小写不敏感）
    DREAM_TRIGGER_WORDS = ("梦", "昨晚", "梦见", "梦到", "dream")

    def __init__(
        self, memory_manager, vector_store=None, embedding_model=None, config: RoutingConfig = None
    ):
        """初始化记忆路由器（缺省使用默认配置）。"""
        self.memory_manager = memory_manager
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.config = config or RoutingConfig()

        # 如果 RoutingConfig 的 max_memories/min_score_threshold 为 None，从 Settings 读取默认值
        limits = Settings().config.limits.memory
        if self.config.max_memories is None:
            self.config.max_memories = limits.max_memories
        if self.config.min_score_threshold is None:
            self.config.min_score_threshold = limits.min_score_threshold

        from server.core.memory.decay import DecayCalculator

        self.decay_calculator = DecayCalculator()

        from server.core.memory.hybrid_search import HybridSearch

        self.hybrid_search = None
        if vector_store and embedding_model:
            self.hybrid_search = HybridSearch(vector_store, memory_manager, embedding_model)

    def set_config(self, config: RoutingConfig):
        """替换路由器的评分配置对象。"""
        self.config = config

    async def route(
        self,
        query: str,
        session_id: str = None,
        scene_type: str = "chat",
        context: Dict = None,
        options: Dict = None,
    ) -> RoutingResult:
        """执行一次记忆路由：聚合检索、评分、过滤、场景调整后返回最终记忆结果；失败时返回空结果并记录 error。"""
        options = options or {}

        applied_rules = []
        applied_weights = self._get_weights(scene_type)
        source_counts = {"permanent": 0, "long_term": 0, "short_term": 0, "dream": 0}

        all_memories = []

        try:
            # A1: _get_recent_memories 内部为同步 SQLite LIKE 查询（热路径逐消息调用），
            # 下放至线程池执行，避免阻塞事件循环；方法本身保持同步签名（有单测直调）
            recent_memories = await asyncio.to_thread(self._get_recent_memories, session_id)
            if recent_memories:
                all_memories.extend(recent_memories)
                applied_rules.append("最近交互记忆优先")

            search_results = await self._search_memories(query, options)

            scored_memories = self._score_memories(
                search_results, query, applied_weights, context or {}
            )

            dream_filtered = self._apply_dream_filter(scored_memories, query, scene_type)

            filtered = self._apply_filters(dream_filtered)

            final_memories = self._apply_scene_adjustment(filtered, scene_type, applied_weights)

            total_score = sum(m.get("final_score", 0) for m in final_memories)

            for m in final_memories:
                mem_type = m.get("type", "long_term")
                if mem_type in source_counts:
                    source_counts[mem_type] += 1

            return RoutingResult(
                memories=final_memories[: self.config.max_memories],
                total_score=total_score,
                source_counts=source_counts,
                applied_weights=applied_weights,
                applied_rules=applied_rules,
                context={
                    "query": query,
                    "scene_type": scene_type,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"记忆路由失败: {e}")
            return RoutingResult(
                memories=[],
                total_score=0.0,
                source_counts=source_counts,
                applied_weights=applied_weights,
                applied_rules=applied_rules,
                context={"error": str(e)},
            )

    def _get_weights(self, scene_type: str) -> Dict[str, float]:
        if not self.config.scene_awareness_enabled:
            return {
                "importance": self.config.importance_weight,
                "time": self.config.time_weight,
                "relevance": self.config.relevance_weight,
            }

        scene_config = self.SCENE_CONFIGS.get(scene_type, self.SCENE_CONFIGS["chat"])
        return {
            "importance": scene_config["importance_weight"],
            "time": scene_config["time_weight"],
            "relevance": scene_config["relevance_weight"],
        }

    def _get_recent_memories(self, session_id: str) -> List[Dict]:
        if not session_id:
            return []

        try:
            # 分页拉取该会话记忆：search_memories 支持 offset，每页推进避免反复取同一批首 20 条
            # （原实现 page += 1 但从未传 offset，导致每轮重复取首窗口并追加重复项）。
            # 目标数为返回上限 100（无需多取 200 再截断），每页 20 条 → 至多 5 页。
            memories = []
            page = 1
            page_size = 20
            max_iterations = 5
            while len(memories) < 100 and page <= max_iterations:
                results = self.memory_manager.search_memories(
                    query=None,
                    memory_type=None,
                    tags=[session_id],
                    limit=page_size,
                    offset=(page - 1) * page_size,
                )
                if not results:
                    break
                for mem in results:
                    if session_id in mem.get("tags", []):
                        memories.append(mem)
                page += 1
            return memories[:100]

        except Exception as e:
            logger.error(f"获取最近记忆失败: {e}")
        return []

    async def _search_memories(self, query: str, options: Dict) -> List[Dict]:
        try:
            limit = options.get("limit", 50)

            if self.hybrid_search and query:
                from server.core.memory.hybrid_search import HybridSearchOptions

                search_options = HybridSearchOptions(
                    query=query,
                    limit=limit,
                    memory_type=options.get("memory_type"),
                    tags=options.get("tags"),
                    vector_weight=0.6,
                    keyword_weight=0.4,
                    min_score=0.2,
                )
                results = await self.hybrid_search.search(search_options)

                memories = []
                for r in results:
                    memory = {
                        "id": r.memory_id,
                        "content": r.content,
                        "score": r.score,
                        "source": r.source,
                        "metadata": r.metadata or {},
                    }
                    # M-D5: 透传混合检索携带的原始评分字段。缺字段时下游
                    # calculate_time_score 会用 datetime.now() 兜底 created_at，
                    # 导致时间通道退化为恒定值——有真实值必须带上。
                    for _k in ("importance", "importance_score", "created_at", "reactivation_count"):
                        _v = getattr(r, _k, None)
                        if _v is not None:
                            memory[_k] = _v
                    memories.append(memory)

                return memories

            # A1: hybrid 不可用时的回退分支同样走同步 SQLite（LIKE 全表扫描），
            # 经 to_thread 下放，避免阻塞事件循环
            return await asyncio.to_thread(
                self.memory_manager.search_memories,
                query=query,
                memory_type=options.get("memory_type"),
                tags=options.get("tags"),
                limit=limit,
            )

        except Exception as e:
            logger.error(f"搜索记忆失败: {e}")
            return []

    def _score_memories(
        self, memories: List[Dict], query: str, weights: Dict[str, float], context: Dict
    ) -> List[Dict]:
        scored = []

        for memory in memories:
            try:
                importance_score = self.decay_calculator.calculate_importance_score(memory)
                time_score = self.decay_calculator.calculate_time_score(memory)
                relevance_score = memory.get("score", 0.5)

                # 梦境召回隔离（红线 R1）：梦境 relevance 降权，避免联想内容抢占真实记忆排序
                if memory.get("type") == "dream" or (memory.get("metadata") or {}).get("type") == "dream":
                    relevance_score = relevance_score * 0.7

                final_score = (
                    importance_score * weights["importance"]
                    + time_score * weights["time"]
                    + relevance_score * weights["relevance"]
                )

                memory["final_score"] = min(final_score, 1.0)
                memory["component_scores"] = {
                    "importance": importance_score,
                    "time": time_score,
                    "relevance": relevance_score,
                }

                scored.append(memory)

            except Exception as e:
                logger.warning(f"记忆评分失败: {e}")
                memory["final_score"] = memory.get("score", 0.3)
                scored.append(memory)

        return scored

    def _apply_filters(self, memories: List[Dict]) -> List[Dict]:
        filtered = []

        for memory in memories:
            score = memory.get("final_score", 0)

            if memory.get("permanent"):
                filtered.append(memory)
                continue

            if score >= self.config.high_priority_threshold:
                filtered.append(memory)
            elif score >= self.config.min_score_threshold:
                filtered.append(memory)
            elif self._is_explicitly_mentioned(memory):
                filtered.append(memory)

        return filtered

    def _is_explicitly_mentioned(self, memory: Dict) -> bool:
        return memory.get("explicitly_mentioned", False)

    def _is_dream_recall_scene(self, query: str, scene_type: str) -> bool:
        """判断当前是否为梦境召回场景：scene_type=='dream_recall' 或查询命中梦境触发词（大小写不敏感）。"""
        if scene_type == "dream_recall":
            return True
        if not query:
            return False
        lowered = query.lower()
        return any(word in lowered for word in self.DREAM_TRIGGER_WORDS)

    def _apply_dream_filter(
        self, memories: List[Dict], query: str, scene_type: str
    ) -> List[Dict]:
        """梦境召回隔离（红线 R1）：默认排除 type='dream' 记忆（不进常规召回结果）；
        仅 dream_recall 场景或查询命中梦境触发词时放行，且仅放行 consolidation_state=='confirmed' 的梦境。
        """
        dream_recall = self._is_dream_recall_scene(query, scene_type)
        filtered = []
        for memory in memories:
            if memory.get("type") == "dream" or (
                (memory.get("metadata") or {}).get("type") == "dream"
            ):
                if not dream_recall:
                    continue
                metadata = memory.get("metadata") or {}
                if metadata.get("consolidation_state") != "confirmed":
                    continue
                # confirmed 梦境在梦境召回场景下视为被显式提起，保证不被分数阈值误伤
                memory["explicitly_mentioned"] = True
            filtered.append(memory)
        return filtered

    def _apply_scene_adjustment(
        self, memories: List[Dict], scene_type: str, weights: Dict[str, float]
    ) -> List[Dict]:
        if scene_type == "task":
            memories.sort(
                key=lambda m: m.get("component_scores", {}).get("relevance", 0), reverse=True
            )
        elif scene_type == "first_interaction":
            for m in memories:
                m["final_score"] = min(1.0, m.get("final_score", 0) * 1.2)

        return memories

    def get_routing_status(self) -> Dict:
        """返回路由器的启用状态与当前配置。"""
        return {
            "enabled": True,
            "config": {
                "importance_weight": self.config.importance_weight,
                "time_weight": self.config.time_weight,
                "relevance_weight": self.config.relevance_weight,
                "hard_rules_enabled": self.config.hard_rules_enabled,
                "scene_awareness_enabled": self.config.scene_awareness_enabled,
                "max_memories": self.config.max_memories,
                "min_score_threshold": self.config.min_score_threshold,
            },
            "scene_configs": {
                k: {
                    "description": v["description"],
                    "weights": {
                        "importance": v["importance_weight"],
                        "time": v["time_weight"],
                        "relevance": v["relevance_weight"],
                    },
                }
                for k, v in self.SCENE_CONFIGS.items()
            },
        }
