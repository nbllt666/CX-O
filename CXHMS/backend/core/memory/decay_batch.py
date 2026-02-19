import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class BatchDecayResult:
    total: int
    updated: int
    failed: int
    details: List[Dict]


class DecayBatchProcessor:
    def __init__(self, memory_manager, interval_hours: int = 24):
        self.memory_manager = memory_manager
        self.interval_hours = interval_hours
        self._batch_size = 100
        self._task = None
        self._stop_event = asyncio.Event()
        self.decay_calculator = None

    async def start(self):
        """启动批量衰减处理器"""
        if self._task is None:
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_periodically())
            logger.info(f"批量衰减处理器已启动，间隔: {self.interval_hours}小时")

    async def stop(self):
        """停止批量衰减处理器"""
        if self._task:
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
            logger.info("批量衰减处理器已停止")

    async def _run_periodically(self):
        """定期运行衰减处理"""
        while not self._stop_event.is_set():
            try:
                await self.process_batch()
                logger.info("批量衰减处理完成")
            except Exception as e:
                logger.error(f"批量衰减处理失败: {e}")

            # 等待下一次执行或停止信号
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_hours * 3600)
            except asyncio.TimeoutError:
                continue

    async def process_batch(
        self, batch_size: int = 100, sync: bool = False, dry_run: bool = False
    ) -> BatchDecayResult:
        from backend.core.memory.decay import DecayCalculator

        if batch_size > 0:
            self._batch_size = batch_size

        decay_calculator = DecayCalculator()
        memories = self.memory_manager.search_memories(limit=self._batch_size)

        if not memories:
            return BatchDecayResult(total=0, updated=0, failed=0, details=[])

        results = []
        updated_count = 0
        failed_count = 0

        for memory in memories:
            memory_id = memory["id"]
            try:
                decayed_value = decay_calculator.calculate_decay(
                    importance=memory.get("importance_score", 0.6),
                    created_at=memory.get("created_at", datetime.now().isoformat()),
                    decay_type=memory.get("decay_type", "exponential"),
                    decay_params=memory.get("decay_params"),
                )

                if dry_run:
                    results.append(
                        {
                            "memory_id": memory_id,
                            "old_value": memory.get("importance_score", 0.0),
                            "new_value": decayed_value,
                            "dry_run": True,
                        }
                    )
                    updated_count += 1
                else:
                    # 更新记忆的重要性和元数据
                    from backend.core.memory.decay import score_to_importance

                    new_importance = score_to_importance(decayed_value)

                    success = self.memory_manager.update_memory(
                        memory_id=memory_id,
                        new_importance=new_importance,
                        new_metadata={
                            "importance_score": decayed_value,
                            "decay_updated_at": datetime.now().isoformat(),
                        },
                    )

                    if success:
                        results.append(
                            {
                                "memory_id": memory_id,
                                "old_value": memory.get("importance_score", 0.0),
                                "new_value": decayed_value,
                                "updated": True,
                            }
                        )
                        updated_count += 1
                    else:
                        results.append(
                            {"memory_id": memory_id, "error": "Update failed", "updated": False}
                        )
                        failed_count += 1
            except Exception as e:
                logger.error(f"处理记忆失败: {memory_id}, {e}")
                results.append({"memory_id": memory_id, "error": str(e), "updated": False})
                failed_count += 1

        if sync and not dry_run:
            sync_result = self.memory_manager.sync_decay_values()
            logger.info(f"同步衰减值: 更新={sync_result['updated']}, 失败={sync_result['failed']}")

        return BatchDecayResult(
            total=len(memories), updated=updated_count, failed=failed_count, details=results
        )

    async def process_all(
        self, batch_size: int = 100, sync: bool = False, dry_run: bool = False
    ) -> Dict:
        total_updated = 0
        total_failed = 0
        all_details = []
        batch_count = 0

        while True:
            batch_result = await self.process_batch(
                batch_size=batch_size, sync=False, dry_run=dry_run
            )

            batch_count += 1
            total_updated += batch_result.updated
            total_failed += batch_result.failed
            all_details.extend(batch_result.details)

            logger.info(
                f"批次 {batch_count}: 总数={batch_result.total}, "
                f"更新={batch_result.updated}, 失败={batch_result.failed}"
            )

            if batch_result.total < batch_size:
                break

        if sync and not dry_run:
            sync_result = self.memory_manager.sync_decay_values()
            logger.info(f"同步衰减值: 更新={sync_result['updated']}, 失败={sync_result['failed']}")

        return {
            "total_batches": batch_count,
            "total_updated": total_updated,
            "total_failed": total_failed,
            "details": all_details,
        }

    def get_batch_status(self) -> Dict:
        return {
            "batch_size": self._batch_size,
            "memory_manager": self.memory_manager is not None,
            "decay_calculator": self.decay_calculator is not None,
        }
