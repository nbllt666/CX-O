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
        agent_id: str = None,
    ) -> RoutingResult:
        """执行一次记忆路由：聚合检索、评分、过滤、场景调整后返回最终记忆结果；失败时返回空结果并记录 error。

        agent_id：per-agent 向量 collection 检索隔离。不传时 HybridSearchOptions 回退
        默认 "default" collection——多 agent 场景下 chat 链路必须显式传入，否则检索
        不到该 agent 的记忆（检索到但没注入的断裂根因之二，2026-09-12）。
        """
        # 1) query 嵌入只算一次：供 hybrid 混合检索与新增的真实相关性打分共用；
        #    嵌入模型缺失/query 空/返回空或零向量时返回 None（内部兜底，绝不抛出）
        query_embedding = await self._embed_query(query)

        # 1b) 失败状态传递（T5b）：模型可用、query 非空但拿不到向量 = 已尝试且失败
        #     → 下传 hybrid，向量通道跳过重复尝试（等价于嵌入失败 → 向量通道无结果）；
        #     模型缺失/query 空不置位——非"尝试失败"，不影响 hybrid 原有自算回退
        embedding_attempted_failed = (
            query_embedding is None and self.embedding_model is not None and bool(query)
        )

        # 2) options 注入（query 嵌入透传 HybridSearchOptions；agent_id 下传检索与 recent 通道）
        options = options or {}
        options = {
            **options,
            "query_embedding": query_embedding,
            "query_embedding_attempted": embedding_attempted_failed,
        }
        if agent_id:
            options = {**options, "agent_id": agent_id}

        applied_rules = []
        applied_weights = self._get_weights(scene_type)
        source_counts = {"permanent": 0, "long_term": 0, "short_term": 0, "dream": 0}

        try:
            # 3) 会话最近记忆（按 agent 隔离），4) 混合检索；二者按 id 去重合并为统一候选池
            # A1: _get_recent_memories 内部为同步 SQLite LIKE 查询（热路径逐消息调用），
            # 下放至线程池执行，避免阻塞事件循环；方法本身保持同步签名（有单测直调）
            recent_memories = await asyncio.to_thread(
                self._get_recent_memories, session_id, agent_id
            )
            if recent_memories:
                applied_rules.append("最近交互记忆优先")

            search_results = await self._search_memories(query, options, query_embedding)

            # 5) 按 id 去重合并：消除"recent 产出被丢弃但规则仍被宣告"的不一致（检索结果优先）
            merged = self._merge_candidates(recent_memories, search_results)

            # 6) 对无检索分数的候选补算真实相关性（(1+cos)/2），失败保持缺省 0.5
            await self._fill_missing_relevance(
                merged, query, query_embedding, embedding_attempted_failed
            )

            # 7) 统一候选池进入乘法门控评分
            scored_memories = self._score_memories(
                merged, query, applied_weights, context or {}
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

    def _get_recent_memories(self, session_id: str, agent_id: str = None) -> List[Dict]:
        """拉取会话最近记忆（按 session 标签）。

        agent_id（N2）：可选，缺省 None 保持现语义——不向 search_memories 透传该参数，
        由底层缺省 "default"（读 memories 表）处理，签名向后兼容既有单测直调；
        传入非空值时按 per-agent 记忆表隔离读取（route() 下传实际 agent_id）。
        """
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
                kwargs = {
                    "query": None,
                    "memory_type": None,
                    "tags": [session_id],
                    "limit": page_size,
                    "offset": (page - 1) * page_size,
                }
                # agent_id 为 None 时不透传（保持底层缺省 "default" 语义，避免显式 None 语义歧义）
                if agent_id:
                    kwargs["agent_id"] = agent_id
                results = self.memory_manager.search_memories(**kwargs)
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

    async def _embed_query(self, query: str) -> List[float]:
        """计算 query 嵌入（单次复用）。任一失败场景返回 None，绝不抛出：
        embedding_model 为 None / query 为空 / 返回空或全零向量（H14）→ None + debug 日志。
        """
        if self.embedding_model is None or not query:
            logger.debug("query 嵌入跳过（模型缺失或 query 为空）")
            return None

        from server.core.memory.hybrid_search import _is_blank_vector

        try:
            embedding = await self.embedding_model.get_embedding(query)
        except Exception as e:
            logger.warning(f"query 嵌入计算失败，真实相关性降级: {e}")
            return None

        if _is_blank_vector(embedding):
            logger.debug("query 嵌入为空/零向量，真实相关性降级为缺省值")
            return None
        return embedding

    async def _search_memories(
        self, query: str, options: Dict, query_embedding: List[float] = None
    ) -> List[Dict]:
        try:
            limit = options.get("limit", 50)

            if self.hybrid_search and query:
                from server.core.memory.hybrid_search import HybridSearchOptions

                search_options = HybridSearchOptions(
                    query=query,
                    limit=limit,
                    memory_type=options.get("memory_type"),
                    tags=options.get("tags"),
                    agent_id=options.get("agent_id") or "default",
                    vector_weight=0.6,
                    keyword_weight=0.4,
                    min_score=0.2,
                    # query 嵌入一次复用：注入后 hybrid 向量通道不再重复调用嵌入服务；
                    # 缺失/空向量时回退内部自算，行为不变
                    query_embedding=query_embedding,
                    # 失败状态传递（T5b）：调用方已尝试且失败时，向量通道不再重复调用
                    query_embedding_attempted=options.get("query_embedding_attempted", False),
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
            # U6 修复：按 agent_id 条件下传（None 不透传，保持底层缺省语义；与 recent 通道一致）
            fallback_kwargs = {
                "query": query,
                "memory_type": options.get("memory_type"),
                "tags": options.get("tags"),
                "limit": limit,
            }
            _agent = options.get("agent_id")
            if _agent:
                fallback_kwargs["agent_id"] = _agent
            return await asyncio.to_thread(
                self.memory_manager.search_memories, **fallback_kwargs
            )

        except Exception as e:
            logger.error(f"搜索记忆失败: {e}")
            return []

    def _merge_candidates(
        self, recent_memories: List[Dict], search_results: List[Dict]
    ) -> List[Dict]:
        """按 id 去重合并 recent 通道与检索结果，返回统一打分候选池。

        规则（N3）：
        - 同 id 时保留**检索结果**（它带真实 score/source），recent 行仅用于补齐检索形态
          缺失字段（permanent/type/tags/created_at/importance/importance_score/
          reactivation_count/explicitly_mentioned）——保证 `_apply_filters` 的 permanent
          放行与 `_apply_dream_filter` 的 type 判定对同 id 候选仍可见。
        - 仅当检索条目该键缺失或为 None 时才用 recent 值覆盖。
        - 顺序：检索结果在前、recent 独有项在后，避免影响既有排序稳定性。
        """
        merged: List[Dict] = list(search_results)
        index = {m.get("id"): m for m in merged if m.get("id") is not None}
        fill_keys = (
            "permanent",
            "type",
            "tags",
            "created_at",
            "importance",
            "importance_score",
            "reactivation_count",
            "explicitly_mentioned",
        )

        for recent in recent_memories:
            rid = recent.get("id")
            if rid is not None and rid in index:
                target = index[rid]
                for key in fill_keys:
                    if target.get(key) is None and recent.get(key) is not None:
                        target[key] = recent.get(key)
                continue
            if rid is not None:
                index[rid] = recent
            merged.append(recent)

        return merged

    async def _fill_missing_relevance(
        self,
        memories: List[Dict],
        query: str,
        query_embedding: List[float],
        embedding_attempted_failed: bool = False,
    ) -> None:
        """对**无 "score" 键**的候选批量补算真实相关性并写入 `memory["score"]`。

        覆盖 recent 通道产物与 hybrid 不可用时的 SQL LIKE 回退产物（无检索分数来源）。
        - 目标为空 / embedding_model 为 None / query 空 → 直接返回（保持缺省 0.5，记 warning）
        - query_embedding 为 None 时：若调用方已尝试且失败（embedding_attempted_failed=True，
          U5 失败状态传递，与 T5b 同一语义）→ 直接返回不补算（避免重复 ≈2s 嵌入尝试）；
          否则补算一次（失败则返回）
        - H14 对齐契约：批量嵌入条目数与输入不一致 → 整体弃用（一条都不写），不得按位置错配
        - 逐条 `(1+cos)/2` 映射 [0,1]（与 weaviate `(2-distance)/2` 同尺度）；空向量跳过
        - 全过程 try/except 包裹：任何异常 → warning + 保持缺省，绝不抛出
        """
        try:
            targets = [m for m in memories if "score" not in m]
            if not targets:
                return
            if self.embedding_model is None or not query:
                logger.warning(
                    "无检索分数候选 %d 条，嵌入模型缺失或 query 为空，保持缺省相关性 0.5",
                    len(targets),
                )
                return

            q_embedding = query_embedding
            if not q_embedding:
                # U5 修复：调用方已尝试且失败 → 不重复补算（保持缺省相关性）
                if embedding_attempted_failed:
                    logger.warning(
                        "query 嵌入已尝试且失败，%d 条无检索分数候选保持缺省相关性 0.5",
                        len(targets),
                    )
                    return
                q_embedding = await self._embed_query(query)
            if not q_embedding:
                logger.warning(
                    "query 嵌入不可用，%d 条无检索分数候选保持缺省相关性 0.5", len(targets)
                )
                return

            from server.core.memory.hybrid_search import _is_blank_vector

            texts = [str(m.get("content", ""))[:256] for m in targets]
            embeddings = await self.embedding_model.get_embeddings(texts)

            # H14 对齐契约：条目数不一致整体弃用（不得按位置错配）
            if not embeddings or len(embeddings) != len(targets):
                logger.warning(
                    "批量嵌入条目数不一致(%s != %d)，整体弃用真实相关性，保持缺省 0.5",
                    len(embeddings) if embeddings else 0,
                    len(targets),
                )
                return

            for memory, emb in zip(targets, embeddings):
                if _is_blank_vector(emb):
                    continue
                sim = self._cosine_similarity(q_embedding, emb)
                if sim is None:
                    continue
                sim = max(-1.0, min(1.0, sim))
                memory["score"] = (1.0 + sim) / 2.0

        except Exception as e:
            logger.warning(f"真实相关性计算失败，保持缺省相关性: {e}")

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]):
        """纯 Python 余弦相似度（不引入 numpy）；维度不一致或模长为 0 时返回 None。"""
        try:
            if not a or not b or len(a) != len(b):
                return None
            dot = 0.0
            norm_a = 0.0
            norm_b = 0.0
            for x, y in zip(a, b):
                dot += x * y
                norm_a += x * x
                norm_b += y * y
            if norm_a <= 0 or norm_b <= 0:
                return None
            return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))
        except Exception:
            return None

    def _score_memories(
        self, memories: List[Dict], query: str, weights: Dict[str, float], context: Dict
    ) -> List[Dict]:
        """对候选记忆执行三维评分（归一化乘法门控）。

        公式：``final = relevance × (w_i·importance + w_t·time) / (w_i + w_t)``，结果 clamp [0,1]。
        - **relevance 为乘性门控**：importance/time 不可补偿零相关（relevance=0 → final=0）；
          弱相关候选的分数上界即其 relevance，无法被 importance/time 抬过阈值。
        - 分母 ``w_i + w_t`` 归一化：满分候选（relevance/importance/time 均为 1）上界恒为 1.0。
        - ``relevance_weight`` 仅保留为兼容字段（配置与 applied_weights 输出不变），不再进入公式。
        - 分母 <=0 的防御：权重和为 0 时无法归一化，退化为 0 分（避免除零）。
        - 保留：梦境 R1 降权（relevance×0.7，先降权再进公式）、``component_scores`` 三键结构。
        """
        scored = []

        w_i = weights.get("importance", 0.0)
        w_t = weights.get("time", 0.0)
        weight_sum = w_i + w_t

        for memory in memories:
            try:
                importance_score = self.decay_calculator.calculate_importance_score(memory)
                time_score = self.decay_calculator.calculate_time_score(memory)
                relevance_score = memory.get("score", 0.5)

                # 梦境召回隔离（红线 R1）：梦境 relevance 降权，避免联想内容抢占真实记忆排序
                # （先降权再进公式，降权语义与旧版一致）
                if memory.get("type") == "dream" or (memory.get("metadata") or {}).get("type") == "dream":
                    relevance_score = relevance_score * 0.7

                if weight_sum > 0:
                    base_score = (importance_score * w_i + time_score * w_t) / weight_sum
                else:
                    # 防御：权重全为 0 无法归一化，基础分取 0（不参与门控抬分，避免除零）
                    base_score = 0.0

                final_score = relevance_score * base_score

                memory["final_score"] = max(0.0, min(final_score, 1.0))
                memory["component_scores"] = {
                    "importance": importance_score,
                    "time": time_score,
                    "relevance": relevance_score,
                }

                scored.append(memory)

            except Exception as e:
                # N4 异常兜底分支（显式登记语义）：单条候选评分抛异常时以原始检索分
                # （缺省 0.3）作为最后防线，**不参与乘法门控**、记 warning，仅用于避免
                # 单条候选异常拖垮整轮路由；不得据此判定候选相关性。
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
            memories.sort(key=lambda m: m.get("final_score", 0), reverse=True)
        else:
            # chat 等其余场景：按综合分（含时间衰减与重要性）排序。
            # 不排序则注入窗口取的是 hybrid 检索序（纯相关性）——衰减/重要性/背景
            # 竞争全部无法传导到注入出口，"该忘的忘不掉"（2026-09-13 实测根因）。
            memories.sort(key=lambda m: m.get("final_score", 0), reverse=True)

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
