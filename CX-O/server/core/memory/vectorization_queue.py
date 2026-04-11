import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class VectorizationTask:
    task_id: str
    memory_id: int
    content: str
    embedding: Optional[List[float]] = None
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0


class VectorizationQueue:
    def __init__(
        self,
        embedding_model,
        vector_store,
        max_size: int = 1000,
        batch_size: int = 32,
        process_interval: float = 1.0,
    ):
        self.embedding_model = embedding_model
        self.vector_store = vector_store

        self._queue: Deque[VectorizationTask] = deque(maxlen=max_size)
        self._processing = False
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

        self.batch_size = batch_size
        self.process_interval = process_interval

        self._results: Dict[str, VectorizationTask] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        if self._task is None:
            self._processing = True
            self._stop_event.clear()
            self._task = asyncio.create_task(self._process_loop())
            logger.info("向量化队列处理器已启动")

    async def stop(self):
        if self._task:
            self._processing = False
            self._stop_event.set()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
            logger.info("向量化队列处理器已停止")

    async def add_task(
        self, memory_id: int, content: str, callback: Optional[Callable] = None
    ) -> str:
        task_id = f"{memory_id}_{datetime.now().timestamp()}"

        async with self._lock:
            task = VectorizationTask(task_id=task_id, memory_id=memory_id, content=content)

            self._queue.append(task)
            self._results[task_id] = task

            if callback:
                if task_id not in self._callbacks:
                    self._callbacks[task_id] = []
                self._callbacks[task_id].append(callback)

        logger.debug(f"任务已添加: task_id={task_id}, memory_id={memory_id}")
        return task_id

    async def add_batch(self, items: List[Dict]) -> List[str]:
        task_ids = []
        for item in items:
            memory_id = item["memory_id"]
            content = item["content"]
            task_id = await self.add_task(memory_id, content)
            task_ids.append(task_id)
        return task_ids

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        async with self._lock:
            task = self._results.get(task_id)
            if not task:
                return None

            return {
                "task_id": task.task_id,
                "memory_id": task.memory_id,
                "status": task.status,
                "created_at": task.created_at,
                "completed_at": task.completed_at,
                "error": task.error,
                "retry_count": task.retry_count,
            }

    async def _process_loop(self):
        while self._processing and not self._stop_event.is_set():
            try:
                await self._process_batch()
            except Exception as e:
                logger.error(f"批处理出错: {e}")

            await asyncio.sleep(self.process_interval)

    async def _process_batch(self):
        batch = []
        async with self._lock:
            for _ in range(min(self.batch_size, len(self._queue))):
                if self._queue:
                    batch.append(self._queue.popleft())

        if not batch:
            return

        contents = [task.content for task in batch]
        memory_ids = [task.memory_id for task in batch]

        try:
            embeddings = await self.embedding_model.get_embeddings(contents)

            async with self._lock:
                for i, task in enumerate(batch):
                    task.embedding = embeddings[i]
                    task.status = "embedding_ready"

        except Exception as e:
            logger.error(f"批量获取embedding失败: {e}")
            async with self._lock:
                for task in batch:
                    task.status = "failed"
                    task.error = str(e)

        for task in batch:
            if task.status == "embedding_ready" and task.embedding:
                success = await self.vector_store.add_memory_vector(
                    memory_id=task.memory_id,
                    content=task.content,
                    embedding=task.embedding,
                )

                async with self._lock:
                    if success:
                        task.status = "completed"
                        task.completed_at = datetime.now().isoformat()
                        logger.debug(f"向量化完成: task_id={task.task_id}")
                    else:
                        task.status = "failed"
                        task.error = "Failed to add to vector store"

                    await self._notify_callbacks(task)

    async def _notify_callbacks(self, task: VectorizationTask):
        callbacks = self._callbacks.get(task.task_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task)
                else:
                    callback(task)
            except Exception as e:
                logger.error(f"回调执行失败: {e}")

        if task.task_id in self._callbacks:
            del self._callbacks[task.task_id]

    def get_queue_status(self) -> Dict:
        return {
            "queue_size": len(self._queue),
            "processing": self._processing,
            "batch_size": self.batch_size,
            "process_interval": self.process_interval,
            "results_count": len(self._results),
        }

    async def clear_completed(self, older_than_hours: int = 24):
        cutoff = datetime.now().timestamp() - older_than_hours * 3600

        async with self._lock:
            to_remove = []
            for task_id, task in self._results.items():
                if task.status in ("completed", "failed"):
                    try:
                        created_ts = datetime.fromisoformat(task.created_at).timestamp()
                        if created_ts < cutoff:
                            to_remove.append(task_id)
                    except Exception:
                        pass

            for task_id in to_remove:
                del self._results[task_id]

        logger.info(f"清理了 {len(to_remove)} 个已完成任务")