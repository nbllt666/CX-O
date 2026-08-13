"""server.core.memory.vectorization_queue (VectorizationQueue) 单元测试。

覆盖任务优先级排序、任务入队/状态/统计、工作线程成功/失败/重试、
回调触发、生命周期与单例。

因 VectorizationQueue 为单例且工作线程为 daemon，fixture 重置单例，
工作线程部分用真实线程 + 完成事件轮询，避免挂死。
运行：python -m pytest tests/test_vectorization_queue.py -v
"""
import time

import pytest

from server.core.memory.vectorization_queue import (
    TaskStatus,
    VectorizationQueue,
    VectorizationTask,
)


@pytest.fixture
def q():
    """独立单例队列（默认不启动工作线程）。"""
    VectorizationQueue._instance = None
    queue = VectorizationQueue(max_workers=1, batch_size=5)
    yield queue
    queue.stop()
    VectorizationQueue._instance = None


# ---------------------------------------------------------------- 任务优先级
class TestVectorizationTask:
    def test_lower_priority_first(self):
        t1 = VectorizationTask(memory_id="1", content="a", priority=1)
        t2 = VectorizationTask(memory_id="2", content="b", priority=5)
        assert t1 < t2

    def test_priority_instantly(self):
        t1 = VectorizationTask(memory_id="1", content="a", priority=5)
        t2 = VectorizationTask(memory_id="2", content="b", priority=5)
        assert (t1 < t2) == (t1.created_at < t2.created_at)

    def test_defaults(self):
        t = VectorizationTask(memory_id="m", content="c")
        assert t.priority == 5
        assert t.status == TaskStatus.PENDING
        assert t.retry_count == 0
        assert t.max_retries == 3
        assert t.error_message is None
        assert t.completed_at is None


# ---------------------------------------------------------------- 入队与状态
class TestTaskLifecycle:
    def test_add_task_returns_id(self, q):
        assert q.add_task("m1", "内容") == "m1"

    def test_add_task_status_pending(self, q):
        q.add_task("m1", "内容", priority=2)
        status = q.get_task_status("m1")
        assert status["status"] == "pending"
        assert status["priority"] == 2
        assert status["retry_count"] == 0

    def test_get_status_missing_returns_none(self, q):
        assert q.get_task_status("nope") is None

    def test_add_task_increments_stats(self, q):
        q.add_task("m1", "a")
        q.add_task("m2", "b")
        stats = q.get_stats()
        assert stats["total_tasks"] == 2
        assert stats["pending_tasks"] == 2

    def test_priority_queue_order(self, q):
        # 高优先级（数字小）先出队
        q.add_task("low", "low", priority=9)
        q.add_task("high", "high", priority=1)
        first = q._queue.get()
        assert first.memory_id == "high"
        second = q._queue.get()
        assert second.memory_id == "low"


# ---------------------------------------------------------------- 工作线程
class TestWorker:
    def _poll(self, q, memory_id, expect, timeout=3.0):
        """轮询直到任务状态变为 expect。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = q.get_task_status(memory_id)
            if status and status["status"] == expect:
                return status
            time.sleep(0.02)
        return q.get_task_status(memory_id)

    def test_process_success(self, q):
        completed = []
        q.set_callbacks(on_complete=lambda mid, content: completed.append((mid, content)), on_error=None)
        q.add_task("m1", "hello")
        q.start()
        status = self._poll(q, "m1", "completed")
        q.stop()
        assert status["status"] == "completed"
        assert status["completed_at"] is not None
        assert completed == [("m1", "hello")]
        assert q.get_stats()["completed_tasks"] == 1

    def test_process_retry_then_success(self, q):
        calls = {"n": 0}
        last_error = {"v": None}

        def flaky_on_complete(mid, content):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("第一次失败")
            return

        def on_error(mid, err):
            last_error["v"] = err

        q.set_callbacks(on_complete=flaky_on_complete, on_error=on_error)
        q.add_task("m1", "hello")
        q.start()
        status = self._poll(q, "m1", "completed", timeout=4.0)
        q.stop()
        assert status["status"] == "completed"
        assert calls["n"] == 2
        assert last_error["v"] is None

    def test_process_failure_after_max_retries(self, q):
        calls = {"n": 0}
        errors = []

        def always_fail(mid, content):
            calls["n"] += 1
            raise ValueError("boom")

        def on_error(mid, err):
            errors.append((mid, str(err)))

        q.set_callbacks(on_complete=always_fail, on_error=on_error)
        q.add_task("m1", "hello")
        q.start()
        status = self._poll(q, "m1", "failed", timeout=4.0)
        q.stop()
        assert status["status"] == "failed"
        assert status["error_message"] == "boom"
        assert calls["n"] == 3  # max_retries=3
        assert errors == [("m1", "boom")]
        assert q.get_stats()["failed_tasks"] == 1

    def test_start_twice_warns_no_dup(self, q, monkeypatch):
        warnings = []
        monkeypatch.setattr(
            "server.core.memory.vectorization_queue.logger.warning",
            lambda msg: warnings.append(msg),
        )
        q.start()
        q.start()
        assert len(q._workers) == 1
        assert any("already started" in w for w in warnings)
        q.stop()

    def test_stop_joins_workers(self, q):
        q.add_task("m1", "hello")
        q.start()
        q.stop()
        assert q._workers == []
        assert q._stop_event.is_set()