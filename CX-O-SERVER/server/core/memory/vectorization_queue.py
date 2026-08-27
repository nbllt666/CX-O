"""
异步向量化队列 - 将记忆向量化操作改为异步处理

解决记忆创建阻塞问题，提高响应速度
"""
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from queue import Empty, PriorityQueue
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class VectorizationTask:
    """向量化任务"""
    memory_id: str
    content: str
    priority: int = 5  # 1-10，数字越小优先级越高
    created_at: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
    
    def __lt__(self, other):
        """用于优先级队列比较"""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


class VectorizationQueue:
    """向量化任务队列"""

    _instance = None
    _lock = threading.Lock()

    # 终态（COMPLETED/FAILED）条目保留上限：防止 _task_status 字典只进不出导致内存无界增长
    _MAX_TERMINAL_RECORDS = 200
    _TERMINAL_STATUSES = (TaskStatus.COMPLETED, TaskStatus.FAILED)
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, max_workers: int = 2, batch_size: int = 5):
        """初始化队列
        
        Args:
            max_workers: 最大工作线程数
            batch_size: 批量处理大小
        """
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.max_workers = max_workers
        self.batch_size = batch_size
        
        # 任务队列（优先级队列）
        self._queue = PriorityQueue()
        
        # 任务状态跟踪
        self._task_status: Dict[str, VectorizationTask] = {}
        self._status_lock = threading.Lock()
        
        # 工作线程
        self._workers: List[threading.Thread] = []
        self._stop_event = threading.Event()
        
        # 回调函数
        self._on_complete_callback: Optional[Callable] = None
        self._on_error_callback: Optional[Callable] = None
        
        # 统计信息
        self._stats = {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "pending_tasks": 0,
            "processing_tasks": 0,
        }
        self._stats_lock = threading.Lock()
        
        self._initialized = True
        logger.info(f"VectorizationQueue initialized (workers={max_workers}, batch_size={batch_size})")
    
    def start(self):
        """启动工作线程"""
        if self._workers:
            logger.warning("Workers already started")
            return
        
        # M3（第五轮）修复: stop() 置位后从不 clear，stop 后再次 start() 的
        # 新 worker 进入 _worker_loop 即因 _stop_event.is_set() 立即退出，
        # 队列永久不可用。start 时一并清除停止事件。
        self._stop_event.clear()
        
        logger.info(f"Starting {self.max_workers} worker threads")
        for i in range(self.max_workers):
            worker = threading.Thread(target=self._worker_loop, name=f"VectorizationWorker-{i}", daemon=True)
            worker.start()
            self._workers.append(worker)
        
        logger.info("All workers started")
    
    def stop(self):
        """停止工作线程"""
        logger.info("Stopping workers...")
        self._stop_event.set()
        
        # 等待所有任务完成
        for worker in self._workers:
            worker.join(timeout=5.0)
        
        self._workers.clear()
        logger.info("All workers stopped")
    
    def set_callbacks(self, on_complete: Callable, on_error: Callable):
        """设置回调函数
        
        Args:
            on_complete: 任务完成回调 on_complete(memory_id, vector)
            on_error: 任务失败回调 on_error(memory_id, error)
        """
        self._on_complete_callback = on_complete
        self._on_error_callback = on_error
    
    def add_task(self, memory_id: str, content: str, priority: int = 5) -> str:
        """添加向量化任务
        
        Args:
            memory_id: 记忆 ID
            content: 需要向量化的内容
            priority: 优先级（1-10，数字越小优先级越高）
            
        Returns:
            memory_id
        """
        task = VectorizationTask(
            memory_id=memory_id,
            content=content,
            priority=priority
        )
        
        with self._status_lock:
            self._task_status[memory_id] = task
            self._stats["total_tasks"] += 1
            self._stats["pending_tasks"] += 1
        
        self._queue.put(task)
        logger.debug(f"Added vectorization task: {memory_id} (priority={priority})")
        
        return memory_id
    
    def get_task_status(self, memory_id: str) -> Optional[Dict]:
        """获取任务状态
        
        Args:
            memory_id: 记忆 ID
            
        Returns:
            任务状态字典，如果不存在则返回 None
        """
        with self._status_lock:
            task = self._task_status.get(memory_id)
            if not task:
                return None
            
            return {
                "memory_id": task.memory_id,
                "status": task.status.value,
                "priority": task.priority,
                "retry_count": task.retry_count,
                "error_message": task.error_message,
                "created_at": task.created_at.isoformat(),
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            }
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self._stats_lock:
            return self._stats.copy()
    
    def _worker_loop(self):
        """工作线程主循环"""
        logger.debug(f"Worker {threading.current_thread().name} started")
        
        while not self._stop_event.is_set():
            try:
                # 从队列获取任务（带超时）
                try:
                    task = self._queue.get(timeout=1.0)
                except Empty:
                    continue
                
                # 更新任务状态（M3: 移入 try/finally——旧实现位于 try 之外，
                # 该处抛异常会跳过 task_done，PriorityQueue.join 计数失衡永久阻塞）
                # H8: task_done 须在 finally 中保证执行——处理/重试分支任一步
                # 抛异常（含回调、stats、状态更新自身抛错）若跳过 task_done，
                # PriorityQueue.join() 未完成计数失衡，stop/shutdown 永久阻塞。
                try:
                    # 进入 PROCESSING 先补计数——本处理分支各终止/重试路径都会对应 -1，
                    # 旧实现只减不加必致 processing_tasks 变负
                    with self._stats_lock:
                        self._stats["processing_tasks"] += 1

                    self._update_task_status(task.memory_id, TaskStatus.PROCESSING)

                    # 调用完成回调执行实际的向量化操作
                    if self._on_complete_callback:
                        self._on_complete_callback(task.memory_id, task.content)
                    
                    # 更新状态为完成
                    task.completed_at = datetime.now()
                    self._update_task_status(task.memory_id, TaskStatus.COMPLETED)
                    
                    with self._stats_lock:
                        self._stats["completed_tasks"] += 1
                        self._stats["processing_tasks"] -= 1
                    
                    logger.debug(f"Vectorization completed: {task.memory_id}")
                    
                except Exception as e:
                    # 处理失败
                    task.retry_count += 1
                    task.error_message = str(e)
                    
                    if task.retry_count < task.max_retries:
                        # 重试
                        logger.warning(f"Vectorization failed, retrying ({task.retry_count}/{task.max_retries}): {task.memory_id}")
                        task.status = TaskStatus.PENDING
                        self._queue.put(task)
                        with self._stats_lock:
                            self._stats["processing_tasks"] -= 1
                            self._stats["pending_tasks"] += 1
                    else:
                        # 超过最大重试次数，标记为失败
                        logger.error(f"Vectorization failed after {task.max_retries} retries: {task.memory_id}")
                        self._update_task_status(task.memory_id, TaskStatus.FAILED)
                        
                        if self._on_error_callback:
                            self._on_error_callback(task.memory_id, e)
                        
                        with self._stats_lock:
                            self._stats["failed_tasks"] += 1
                            self._stats["processing_tasks"] -= 1
                finally:
                    self._queue.task_done()
                
            except Exception as e:
                logger.error(f"Worker error: {e}", exc_info=True)
        
        logger.debug(f"Worker {threading.current_thread().name} stopped")
    
    def _update_task_status(self, memory_id: str, status: TaskStatus):
        """更新任务状态；转入终态后按插入序从头部裁剪旧终态条目（保留最近 ~200 条）。"""
        with self._status_lock:
            if memory_id in self._task_status:
                self._task_status[memory_id].status = status

            # 终态裁剪：dict 保持插入序（旧条目在前），弹出多余的 COMPLETED/FAILED 条目；
            # PENDING/PROCESSING 条目不参与计数，不会误删未完成任务
            if status in self._TERMINAL_STATUSES:
                terminal_ids = [
                    mid for mid, t in self._task_status.items()
                    if t.status in self._TERMINAL_STATUSES
                ]
                for mid in terminal_ids[: max(0, len(terminal_ids) - self._MAX_TERMINAL_RECORDS)]:
                    del self._task_status[mid]
