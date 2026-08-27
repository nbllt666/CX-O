"""server.core.memory.decay_batch (DecayBatchProcessor) 单元测试。

覆盖批量衰减处理、dry_run、更新成功/失败、多批遍历、生命周期与状态。
运行：python -m pytest tests/test_decay_batch.py -v
"""
import asyncio
from datetime import datetime

import pytest

from server.core.memory.decay_batch import BatchDecayResult, DecayBatchProcessor


class FakeMemoryManager:
    def __init__(self, memories):
        self.memories = memories
        self.updates = []
        self.sync_calls = 0

    def search_memories(self, limit=100, offset=0):
        return self.memories[offset : offset + limit]

    async def update_memory_async(self, memory_id, new_importance, new_metadata):
        self.updates.append((memory_id, new_importance, new_metadata))
        return True

    def sync_decay_values(self):
        self.sync_calls += 1
        return {"updated": 1, "failed": 0}


def _mem(mid, importance_score=0.8, created_at=None):
    return {
        "id": mid,
        "importance_score": importance_score,
        "created_at": created_at or datetime.now().isoformat(),
        "decay_type": "exponential",
        "decay_params": None,
    }


@pytest.fixture
def processor():
    mgr = FakeMemoryManager([_mem(1), _mem(2), _mem(3)])
    return DecayBatchProcessor(memory_manager=mgr, interval_hours=24)


class TestResultDefault:
    def test_defaults(self):
        r = BatchDecayResult(0, 0, 0, [])
        assert r.total == 0
        assert r.updated == 0
        assert r.failed == 0
        assert r.details == []


class TestProcessBatch:
    @pytest.mark.asyncio
    async def test_empty_memories(self, processor):
        processor.memory_manager.memories = []
        r = await processor.process_batch()
        assert r.total == 0
        assert r.updated == 0
        assert r.failed == 0

    @pytest.mark.asyncio
    async def test_dry_run_no_update(self, processor):
        r = await processor.process_batch(dry_run=True)
        assert r.total == 3
        assert r.updated == 3
        assert r.failed == 0
        assert processor.memory_manager.updates == []
        assert all(d["dry_run"] for d in r.details)

    @pytest.mark.asyncio
    async def test_real_update_calls(self, processor):
        r = await processor.process_batch()
        assert r.updated == 3
        assert len(processor.memory_manager.updates) == 3
        # 老化后重要性应下降（衰减）
        for mid, imp, meta in processor.memory_manager.updates:
            assert meta["importance_score"] < 0.8
            assert "decay_updated_at" in meta

    @pytest.mark.asyncio
    async def test_h9_metadata_merged_not_replaced(self):
        """H9: 衰减更新必须保留旧 metadata 原字段（如 dream consolidation_state），
        只在其上合并 importance_score/decay_updated_at——不允许两键覆写清空。"""
        mem = _mem(7)
        mem["metadata"] = {
            "type": "dream",
            "consolidation_state": "confirmed",
            "dream_session_id": "sess-1",
        }
        mgr = FakeMemoryManager([mem])
        p = DecayBatchProcessor(memory_manager=mgr)
        r = await p.process_batch()
        assert r.updated == 1
        mid, imp, meta = mgr.updates[0]
        # 原字段保留
        assert meta["consolidation_state"] == "confirmed"
        assert meta["type"] == "dream"
        assert meta["dream_session_id"] == "sess-1"
        # 衰减字段已合并
        assert "decay_updated_at" in meta
        assert meta["importance_score"] < 0.8

    @pytest.mark.asyncio
    async def test_update_without_legacy_metadata_key(self, processor):
        """快照条目缺 metadata 键时以空 dict 兜底，不抛异常。"""
        r = await processor.process_batch()
        for _, _, meta in processor.memory_manager.updates:
            assert isinstance(meta, dict)

    @pytest.mark.asyncio
    async def test_update_failure_counts_failed(self, processor):
        async def _fail(*a, **k):
            return False

        processor.memory_manager.update_memory_async = _fail
        r = await processor.process_batch()
        assert r.updated == 0
        assert r.failed == 3

    @pytest.mark.asyncio
    async def test_sync_called_when_sync(self, processor):
        await processor.process_batch(sync=True)
        assert processor.memory_manager.sync_calls == 1

    @pytest.mark.asyncio
    async def test_sync_not_called_for_dry_run(self, processor):
        await processor.process_batch(sync=True, dry_run=True)
        assert processor.memory_manager.sync_calls == 0


class TestProcessAll:
    @pytest.mark.asyncio
    async def test_single_batch(self, processor):
        result = await processor.process_all(batch_size=10, dry_run=True)
        assert result["total_batches"] == 1
        assert result["total_updated"] == 3
        assert result["total_failed"] == 0

    @pytest.mark.asyncio
    async def test_multiple_batches(self):
        # 3 条记忆，batch_size=2 → 2 批
        mgr = FakeMemoryManager([_mem(i) for i in range(1, 4)])
        p = DecayBatchProcessor(memory_manager=mgr)
        result = await p.process_all(batch_size=2, dry_run=True)
        assert result["total_batches"] == 2


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self, processor):
        await processor.start()
        assert processor._task is not None
        await processor.stop()
        assert processor._task is None

    @pytest.mark.asyncio
    async def test_periodic_uses_process_all_full_coverage(self, processor):
        """M-D2: 周期后台任务必须走 process_all 全量快照，而非默认
        process_batch(top100)——后者使尾部低分记忆饥饿。"""
        calls = {"n": 0}

        async def _fake_process_all(*a, **k):
            calls["n"] += 1
            return {"total_batches": 1, "total_updated": 3, "total_failed": 0, "details": []}

        processor.process_all = _fake_process_all
        real_stop_wait = processor._stop_event.wait

        def _stop_event_wait(timeout=None):
            # 第一轮周期结束后立即置位停止信号收口
            if calls["n"] >= 1:
                processor._stop_event.set()
            return real_stop_wait()

        processor._stop_event.wait = _stop_event_wait
        task = asyncio.create_task(processor._run_periodically())
        await asyncio.wait_for(task, timeout=2.0)
        # 周期处理调用的是 process_all 且已执行
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_start_idempotent(self, processor):
        await processor.start()
        task1 = processor._task
        await processor.start()
        assert processor._task is task1
        await processor.stop()

    @pytest.mark.asyncio
    async def test_get_batch_status(self, processor):
        status = processor.get_batch_status()
        assert status["batch_size"] == 100
        assert status["memory_manager"] is True
        assert status["decay_calculator"] is False