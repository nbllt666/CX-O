"""MemoryManager mixin: Vector store integration (sync, search, health).

Extracted from manager.py as part of H5 mixin split.
"""
import asyncio
from typing import Dict, List, TYPE_CHECKING


from ._common import logger

if TYPE_CHECKING:
    pass


class _VectorIntegrationMixin:
    """Vector integration mixin: vector store operations and async search."""
    def _init_advanced_components(self):
        """初始化高级组件（归档器、去重引擎）"""
        try:
            from server.core.memory.archiver import AdvancedArchiver

            self.archiver = AdvancedArchiver(self)
            logger.info("归档器已初始化")
        except Exception as e:
            logger.warning(f"归档器初始化失败: {e}")
            self.archiver = None

        try:
            from server.core.memory.deduplication import DeduplicationEngine

            self.deduplication_engine = DeduplicationEngine(self)
            logger.info("去重引擎已初始化")
        except Exception as e:
            logger.warning(f"去重引擎初始化失败: {e}")
            self.deduplication_engine = None

        try:
            from server.core.memory.vectorization_queue import VectorizationQueue

            self.vectorization_queue = VectorizationQueue(max_workers=2, batch_size=5)
            self.vectorization_queue.set_callbacks(
                on_complete=self._on_vectorization_complete,
                on_error=self._on_vectorization_error
            )
            self.vectorization_queue.start()
            logger.info("向量化队列已初始化并启动")
        except Exception as e:
            logger.warning(f"向量化队列初始化失败：{e}")
            self.vectorization_queue = None

    def _on_vectorization_complete(self, memory_id: str, content: str, agent_id: str = "default"):
        """向量化完成回调 - 执行实际的向量化并存储

        Args:
            memory_id: 记忆 ID
            content: 需要向量化的内容
            agent_id: Agent ID，用于指定 per-agent collection
        """
        logger.debug(f"向量化开始：memory_id={memory_id}, agent_id={agent_id}")

        if not self._vector_store or not self._embedding_model:
            logger.warning(f"向量存储或嵌入模型未初始化，跳过向量化：memory_id={memory_id}")
            return

        try:
            # 在工作线程中执行异步向量化
            async def _do_vectorization():
                # 获取向量
                embedding = await self._embedding_model.get_embedding(content)
                # 存储到向量数据库（per-agent collection）
                return await self._vector_store.add_memory_vector(
                    memory_id=int(memory_id),
                    content=content,
                    embedding=embedding,
                    agent_id=agent_id,
                )

            result = self._run_async_sync(_do_vectorization())
            if result:
                logger.info(f"向量化完成并存储：memory_id={memory_id}, agent_id={agent_id}")
            else:
                logger.warning(f"向量化存储失败：memory_id={memory_id}, agent_id={agent_id}")

        except Exception as e:
            logger.error(f"向量化处理失败：memory_id={memory_id}, agent_id={agent_id}, error={e}")
        
    def _on_vectorization_error(self, memory_id: str, error: Exception):
        """向量化失败回调"""
        logger.error(f"向量化失败：memory_id={memory_id}, error={error}")

    def _run_async_sync(self, coro):
        """在同步方法中运行异步协程

        Args:
            coro: 异步协程对象

        Returns:
            协程的返回值
        """
        import concurrent.futures

        def run_in_new_loop():
            return asyncio.run(coro)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_new_loop)
            return future.result()

    def _sync_vector_for_memory(self, memory_id: int, content: str, metadata: Dict = None) -> bool:
        """同步记忆到向量数据库（异步非阻塞）

        使用向量化队列进行异步处理，立即返回，不阻塞主线程。
        agent_id 从 metadata.agent_id 提取（若有），否则使用 "default"，
        分发到对应的 per-agent collection。

        Args:
            memory_id: 记忆 ID
            content: 记忆内容
            metadata: 元数据（含 agent_id）

        Returns:
            是否同步成功（总是返回 True，因为异步处理）
        """
        if not self._vector_store or not self._embedding_model:
            logger.debug(f"向量存储或嵌入模型未启用，跳过向量同步：memory_id={memory_id}")
            return False

        # 从 metadata 提取 agent_id
        agent_id = "default"
        if metadata and metadata.get("agent_id"):
            agent_id = metadata["agent_id"]

        # 如果向量化队列可用，使用异步处理
        if self.vectorization_queue:
            # 将向量化任务添加到队列（队列内部回调 _on_vectorization_complete 时传 agent_id）
            # 注意：当前 vectorization_queue.add_task 不支持 agent_id 参数，
            # 因此对 per-agent 的向量化走同步路径以保证 agent_id 透传
            try:
                async def _sync_async():
                    embedding = await self._embedding_model.get_embedding(content)
                    return await self._vector_store.add_memory_vector(
                        memory_id=memory_id,
                        content=content,
                        embedding=embedding,
                        metadata=metadata,
                        agent_id=agent_id,
                    )

                result = self._run_async_sync(_sync_async())
                if result:
                    logger.info(f"向量同步成功：memory_id={memory_id}, agent_id={agent_id}")
                return result
            except Exception as e:
                logger.warning(f"向量同步失败：memory_id={memory_id}, agent_id={agent_id}, error={e}")
                return False

        try:

            async def _sync():
                embedding = await self._embedding_model.get_embedding(content)
                return await self._vector_store.add_memory_vector(
                    memory_id=memory_id, content=content, embedding=embedding,
                    metadata=metadata, agent_id=agent_id,
                )

            result = self._run_async_sync(_sync())
            if result:
                logger.info(f"向量同步成功：memory_id={memory_id}, agent_id={agent_id}")
            return result
        except Exception as e:
            logger.warning(f"向量同步失败：memory_id={memory_id}, agent_id={agent_id}, error={e}")
            return False

    def _update_vector_for_memory(
        self, memory_id: int, content: str, metadata: Dict = None
    ) -> bool:
        """更新记忆的向量（在 per-agent collection 中）

        Args:
            memory_id: 记忆ID
            content: 新的记忆内容
            metadata: 新的元数据（含 agent_id）

        Returns:
            是否更新成功
        """
        if not self._vector_store or not self._embedding_model:
            logger.debug(f"向量存储或嵌入模型未启用，跳过向量更新: memory_id={memory_id}")
            return False

        # 从 metadata 提取 agent_id
        agent_id = "default"
        if metadata and metadata.get("agent_id"):
            agent_id = metadata["agent_id"]

        try:

            async def _update():
                await self._vector_store.delete_by_memory_id(memory_id, agent_id=agent_id)
                embedding = await self._embedding_model.get_embedding(content)
                return await self._vector_store.add_memory_vector(
                    memory_id=memory_id, content=content, embedding=embedding,
                    metadata=metadata, agent_id=agent_id,
                )

            result = self._run_async_sync(_update())
            if result:
                logger.info(f"向量更新成功: memory_id={memory_id}, agent_id={agent_id}")
            return result
        except Exception as e:
            logger.warning(f"向量更新失败: memory_id={memory_id}, agent_id={agent_id}, error={e}")
            return False

    def _delete_vector_for_memory(self, memory_id: int, agent_id: str = "default") -> bool:
        """删除记忆的向量（在 per-agent collection 中）

        Args:
            memory_id: 记忆ID
            agent_id: Agent ID，用于指定 per-agent collection

        Returns:
            是否删除成功
        """
        if not self._vector_store:
            logger.debug(f"向量存储未启用，跳过向量删除: memory_id={memory_id}")
            return False

        try:

            async def _delete():
                return await self._vector_store.delete_by_memory_id(memory_id, agent_id=agent_id)

            result = self._run_async_sync(_delete())
            if result:
                logger.info(f"向量删除成功: memory_id={memory_id}, agent_id={agent_id}")
            return result
        except Exception as e:
            logger.warning(f"向量删除失败: memory_id={memory_id}, agent_id={agent_id}, error={e}")
            return False

    def enable_vector_search(
        self,
        embedding_model=None,
        vector_store=None,
        vector_backend: str = "weaviate",
        weaviate_host: str = "localhost",
        weaviate_port: int = 8080,
        weaviate_grpc_port: int = 50051,
        vector_size: int = 768,
        **kwargs,
    ):
        dimension = embedding_model.dimension if embedding_model else vector_size

        self._vector_store_config = {
            "backend": vector_backend,
            "weaviate_host": weaviate_host,
            "weaviate_port": weaviate_port,
            "weaviate_grpc_port": weaviate_grpc_port,
            "vector_size": dimension,
            "embedding_model": embedding_model,
        }

        if vector_store is None:
            try:
                from server.core.memory.vector_store import create_vector_store

                if vector_backend == "weaviate":
                    vector_store = create_vector_store(
                        backend="weaviate",
                        host=weaviate_host,
                        port=weaviate_port,
                        grpc_port=weaviate_grpc_port,
                        vector_size=dimension,
                        embedding_model=embedding_model,
                        **kwargs,
                    )
                elif vector_backend == "weaviate_embedded":
                    vector_store = create_vector_store(
                        backend="weaviate_embedded",
                        vector_size=dimension,
                        embedding_model=embedding_model,
                        **kwargs,
                    )
                else:
                    logger.warning(f"不支持的向量存储后端: {vector_backend}，仅支持 weaviate 和 weaviate_embedded")
                    return

                self._vector_store = vector_store
            except ImportError as e:
                logger.warning(f"向量存储未安装，向量功能不可用: {e}")
                return
        else:
            self._vector_store = vector_store

        self._embedding_model = embedding_model

        if self._vector_store and self._embedding_model:
            from server.core.memory.hybrid_search import HybridSearch

            self._hybrid_search = HybridSearch(
                vector_store=self._vector_store,
                sqlite_manager=self,
                embedding_model=self._embedding_model,
            )
            logger.info(f"向量搜索功能已启用 (后端: {vector_backend})")

    def is_vector_search_enabled(self) -> bool:
        with self._lock:
            return self._hybrid_search is not None and self._vector_store is not None

    async def semantic_search(
        self, query: str, memory_type: str = None, limit: int = 10, agent_id: str = "default"
    ) -> List[Dict]:
        if not self.is_vector_search_enabled():
            return self.search_memories(query=query, memory_type=memory_type, limit=limit, agent_id=agent_id)

        try:
            results = await self._hybrid_search.semantic_search(
                query=query, memory_type=memory_type, limit=limit, agent_id=agent_id
            )
            return results
        except Exception as e:
            logger.error(f"语义搜索失败: {e}")
            return self.search_memories(query=query, memory_type=memory_type, limit=limit, agent_id=agent_id)

    async def hybrid_search(
        self,
        query: str,
        memory_type: str = None,
        tags: List[str] = None,
        limit: int = 10,
        workspace_id: str = None,
        agent_id: str = "default",
    ) -> List[Dict]:
        fallback = False

        if not self.is_vector_search_enabled():
            fallback = True
            results = self.search_memories(
                query=query, memory_type=memory_type, tags=tags, limit=limit, agent_id=agent_id
            )
            for result in results:
                result["fallback"] = fallback
            return results

        try:
            from server.core.memory.hybrid_search import HybridSearchOptions

            options = HybridSearchOptions(
                query=query,
                memory_type=memory_type,
                tags=tags,
                limit=limit,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )

            search_results = await self._hybrid_search.search(options)

            return [
                {
                    "memory_id": r.memory_id,
                    "content": r.content,
                    "score": r.score,
                    "source": r.source,
                    "metadata": r.metadata,
                    "fallback": fallback,
                }
                for r in search_results
            ]
        except Exception as e:
            logger.error(f"混合搜索失败: {e}")
            fallback = True
            results = self.search_memories(
                query=query, memory_type=memory_type, tags=tags, limit=limit, agent_id=agent_id
            )
            for result in results:
                result["fallback"] = fallback
            return results
