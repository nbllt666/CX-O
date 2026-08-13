"""混合检索——向量与关键词等异构检索结果的融合打分与去重。"""
from dataclasses import dataclass
from typing import Dict, List

from server.config import Settings
from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class SearchResult:
    """混合检索的单条结果，携带记忆 ID、内容、融合分数、来源（vector/keyword/hybrid）与元数据。"""
    memory_id: int
    content: str
    score: float
    source: str
    metadata: Dict = None


@dataclass
class HybridSearchOptions:
    """混合检索参数，定义查询、类型/标签过滤、结果上限及各检索通道的权重与开关。"""
    query: str
    memory_type: str = None
    tags: List[str] = None
    limit: int = None
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    min_score: float = None
    use_vector: bool = True
    use_keyword: bool = True
    workspace_id: str = None
    agent_id: str = "default"


class HybridSearch:
    """向量与关键词混合检索的融合打分检索器。"""

    def __init__(self, vector_store, sqlite_manager, embedding_model=None):
        """初始化混合检索器（向量存储、SQLite 管理器与嵌入模型）。"""
        self.vector_store = vector_store
        self.sqlite_manager = sqlite_manager
        self.embedding_model = embedding_model

    async def search(self, options: HybridSearchOptions) -> List[SearchResult]:
        """执行混合检索，融合向量与关键词结果并按分数排序返回。"""
        # 如果 limit 或 min_score 为 None，从 Settings 读取默认值
        limits = Settings().config.limits.memory
        if options.limit is None:
            options.limit = limits.hybrid_search_limit
        if options.min_score is None:
            options.min_score = limits.hybrid_search_min_score

        vector_results = []
        keyword_results = []

        if options.use_vector and options.query and self.vector_store and self.embedding_model:
            vector_results = await self._vector_search(options)

        if options.use_keyword and options.query:
            keyword_results = await self._keyword_search(options)

        merged = self._merge_results(
            vector_results, keyword_results, options.vector_weight, options.keyword_weight
        )

        filtered = [r for r in merged if r.score >= options.min_score]

        filtered.sort(key=lambda x: x.score, reverse=True)

        return filtered[: options.limit]

    async def _vector_search(self, options: HybridSearchOptions) -> List[SearchResult]:
        try:
            embedding = await self.embedding_model.get_embedding(options.query)

            # agent_id 透传到 vector_store（步骤2 完成 weaviate per-agent collection 后生效）
            try:
                vector_results = await self.vector_store.search_similar(
                    query_embedding=embedding,
                    limit=options.limit * 2,
                    memory_type=options.memory_type,
                    agent_id=options.agent_id,
                )
            except TypeError:
                # vector_store 尚未支持 agent_id 参数（步骤2 之前），回退到无 agent_id 调用
                vector_results = await self.vector_store.search_similar(
                    query_embedding=embedding,
                    limit=options.limit * 2,
                    memory_type=options.memory_type,
                )

            return [
                SearchResult(
                    memory_id=r["memory_id"],
                    content=r["content"],
                    score=r["score"],
                    source="vector",
                    metadata=r.get("metadata"),
                )
                for r in vector_results
            ]
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            return []

    async def _keyword_search(self, options: HybridSearchOptions) -> List[SearchResult]:
        try:
            keyword_results = self.sqlite_manager.search_memories(
                query=options.query,
                memory_type=options.memory_type,
                tags=options.tags,
                limit=options.limit * 2,
                agent_id=options.agent_id,
            )

            return [
                SearchResult(
                    memory_id=r["id"],
                    content=r["content"],
                    score=self._calculate_keyword_score(r["content"], options.query),
                    source="keyword",
                    metadata=r,
                )
                for r in keyword_results
            ]
        except Exception as e:
            logger.error(f"关键词搜索失败: {e}")
            return []

    def _calculate_keyword_score(self, content: str, query: str) -> float:
        query_lower = query.lower()
        content_lower = content.lower()

        if query_lower in content_lower:
            position = content_lower.find(query_lower)
            length = len(content_lower)

            base_score = 1.0 - (position / length) if length > 0 else 0.5

            return min(base_score + 0.1, 1.0)

        return 0.1

    def _merge_results(
        self,
        vector_results: List[SearchResult],
        keyword_results: List[SearchResult],
        vector_weight: float,
        keyword_weight: float,
    ) -> List[SearchResult]:
        merged_dict: Dict[int, SearchResult] = {}
        raw_scores: Dict[int, Dict[str, float]] = {}

        for r in vector_results:
            raw_scores[r.memory_id] = {"vector": r.score, "keyword": 0.0}
            merged_dict[r.memory_id] = SearchResult(
                memory_id=r.memory_id,
                content=r.content,
                score=0.0,
                source="vector",
                metadata=r.metadata,
            )

        for r in keyword_results:
            if r.memory_id in raw_scores:
                raw_scores[r.memory_id]["keyword"] = r.score
                merged_dict[r.memory_id].source = "hybrid"
                if r.metadata:
                    merged_dict[r.memory_id].metadata = r.metadata
            else:
                raw_scores[r.memory_id] = {"vector": 0.0, "keyword": r.score}
                merged_dict[r.memory_id] = SearchResult(
                    memory_id=r.memory_id,
                    content=r.content,
                    score=0.0,
                    source="keyword",
                    metadata=r.metadata,
                )

        for memory_id, scores in raw_scores.items():
            merged_dict[memory_id].score = (
                scores["vector"] * vector_weight + scores["keyword"] * keyword_weight
            )

        return list(merged_dict.values())

    async def semantic_search(
        self, query: str, memory_type: str = None, limit: int = 10, agent_id: str = "default"
    ) -> List[Dict]:
        """执行纯向量语义检索（关闭关键词通道），返回结果字典列表。"""
        options = HybridSearchOptions(
            query=query,
            memory_type=memory_type,
            limit=limit,
            use_vector=True,
            use_keyword=False,
            agent_id=agent_id,
        )

        results = await self.search(options)

        return [
            {
                "memory_id": r.memory_id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in results
        ]

    async def keyword_search(
        self, query: str, memory_type: str = None, tags: List[str] = None, limit: int = 10
    ) -> List[Dict]:
        """执行纯关键词检索，返回结果字典列表。"""
        options = HybridSearchOptions(
            query=query,
            memory_type=memory_type,
            tags=tags,
            limit=limit,
            use_vector=False,
            use_keyword=True,
        )

        results = await self.search(options)

        return [
            {
                "memory_id": r.memory_id,
                "content": r.content,
                "score": r.score,
                "metadata": r.metadata,
            }
            for r in results
        ]
