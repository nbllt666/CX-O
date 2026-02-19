from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class SearchResult:
    memory_id: int
    content: str
    score: float
    source: str
    metadata: Dict = None


@dataclass
class HybridSearchOptions:
    query: str
    memory_type: str = None
    tags: List[str] = None
    limit: int = 10
    vector_weight: float = 0.6
    keyword_weight: float = 0.4
    min_score: float = 0.3
    use_vector: bool = True
    use_keyword: bool = True
    workspace_id: str = None


class HybridSearch:
    def __init__(self, vector_store, sqlite_manager, embedding_model=None):
        self.vector_store = vector_store
        self.sqlite_manager = sqlite_manager
        self.embedding_model = embedding_model

    async def search(self, options: HybridSearchOptions) -> List[SearchResult]:
        results: List[SearchResult] = []

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

            vector_results = await self.vector_store.search_similar(
                query_embedding=embedding, limit=options.limit * 2, memory_type=options.memory_type
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

        for r in vector_results:
            if r.memory_id in merged_dict:
                existing = merged_dict[r.memory_id]
                existing.score = existing.score * (1 - vector_weight) + r.score * vector_weight
                existing.content = r.content
            else:
                merged_dict[r.memory_id] = SearchResult(
                    memory_id=r.memory_id,
                    content=r.content,
                    score=r.score * vector_weight,
                    source="vector",
                    metadata=r.metadata,
                )

        for r in keyword_results:
            if r.memory_id in merged_dict:
                existing = merged_dict[r.memory_id]
                combined_score = existing.score * (1 - keyword_weight) + r.score * keyword_weight
                existing.score = combined_score
                existing.source = "hybrid"
                if r.metadata:
                    existing.metadata = r.metadata
            else:
                merged_dict[r.memory_id] = SearchResult(
                    memory_id=r.memory_id,
                    content=r.content,
                    score=r.score * keyword_weight,
                    source="keyword",
                    metadata=r.metadata,
                )

        return list(merged_dict.values())

    async def semantic_search(
        self, query: str, memory_type: str = None, limit: int = 10
    ) -> List[Dict]:
        options = HybridSearchOptions(
            query=query, memory_type=memory_type, limit=limit, use_vector=True, use_keyword=False
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
