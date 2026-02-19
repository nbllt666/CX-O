import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class RoutingResult:
    memories: List[Dict]
    total_score: float
    source_counts: Dict[str, int]
    applied_weights: Dict[str, float]
    applied_rules: List[str]
    context: Dict = field(default_factory=dict)


@dataclass
class RoutingConfig:
    importance_weight: float = 0.35
    time_weight: float = 0.25
    relevance_weight: float = 0.4
    hard_rules_enabled: bool = True
    scene_awareness_enabled: bool = True
    max_memories: int = 10
    min_score_threshold: float = 0.3
    high_priority_threshold: float = 0.8


class MemoryRouter:
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

    def __init__(
        self, memory_manager, vector_store=None, embedding_model=None, config: RoutingConfig = None
    ):
        self.memory_manager = memory_manager
        self.vector_store = vector_store
        self.embedding_model = embedding_model
        self.config = config or RoutingConfig()

        from backend.core.memory.decay import DecayCalculator

        self.decay_calculator = DecayCalculator()

        from backend.core.memory.hybrid_search import HybridSearch, HybridSearchOptions

        self.hybrid_search = None
        if vector_store and embedding_model:
            self.hybrid_search = HybridSearch(vector_store, memory_manager, embedding_model)

    def set_config(self, config: RoutingConfig):
        self.config = config

    async def route(
        self,
        query: str,
        session_id: str = None,
        scene_type: str = "chat",
        context: Dict = None,
        options: Dict = None,
    ) -> RoutingResult:
        options = options or {}

        applied_rules = []
        applied_weights = self._get_weights(scene_type)
        source_counts = {"permanent": 0, "long_term": 0, "short_term": 0}

        all_memories = []

        try:
            recent_memories = self._get_recent_memories(session_id)
            if recent_memories:
                all_memories.extend(recent_memories)
                applied_rules.append("最近交互记忆优先")

            search_results = await self._search_memories(query, options)

            scored_memories = self._score_memories(
                search_results, query, applied_weights, context or {}
            )

            filtered = self._apply_filters(scored_memories)

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
            recent_count = 0
            memories = []
            page = 1
            page_size = 20

            while recent_count < 50:
                results = self.memory_manager.search_memories(
                    query=None,
                    memory_type=None,
                    tags=[session_id] if session_id else None,
                    limit=page_size,
                )

                if not results:
                    break

                for mem in results:
                    if mem.get("session_id") == session_id:
                        memories.append(mem)
                        recent_count += 1

                page += 1

            return memories[:30]

        except Exception as e:
            logger.error(f"获取最近记忆失败: {e}")
        return []

    async def _search_memories(self, query: str, options: Dict) -> List[Dict]:
        try:
            limit = options.get("limit", 50)

            if self.hybrid_search and query:
                from backend.core.memory.hybrid_search import HybridSearchOptions

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
                    memories.append(memory)

                return memories

            return self.memory_manager.search_memories(
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
