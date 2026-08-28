"""批量记忆衰减——后台异步执行大规模记忆的衰减更新。"""
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class BatchDecayResult:
    """单批衰减处理结果，统计处理总数、更新数、失败数及逐条详情。"""
    total: int
    updated: int
    failed: int
    details: List[Dict]


class DecayBatchProcessor:
    """批量记忆衰减处理器，后台按固定间隔异步对记忆执行衰减计算与重要性更新。"""

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
        """定期运行衰减处理。

        M-D2: 周期后台任务改调 process_all()（稳定快照全覆盖）。原实现走
        process_batch() 默认路径 = search(top100 按 importance DESC)，每次
        周期只衰减最头部 100 条，尾部低分记忆永久饥饿。
        """
        while not self._stop_event.is_set():
            try:
                result = await self.process_all()
                logger.info(
                    f"全量衰减处理完成: 批次={result['total_batches']}, "
                    f"更新={result['total_updated']}, 失败={result['total_failed']}"
                )
            except Exception as e:
                logger.error(f"批量衰减处理失败: {e}")

            # 等待下一次执行或停止信号
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_hours * 3600)
            except asyncio.TimeoutError:
                continue

    async def process_batch(
        self,
        batch_size: int = 100,
        sync: bool = False,
        dry_run: bool = False,
        offset: int = 0,
        memories: Optional[List[Dict]] = None,
    ) -> BatchDecayResult:
        """处理一批记忆的衰减更新，返回处理结果。

        memories 为非 None 时为「快照注入路径」：由 process_all 传入稳定
        快照切片，避免逐批 search 依赖 ORDER BY importance 排序键（更新
        importance 会改变排序位置 → offset 分页漂移，漏/重记忆）。
        """
        from server.core.memory.decay import DecayCalculator

        if batch_size > 0:
            self._batch_size = batch_size

        decay_calculator = DecayCalculator()
        if memories is None:
            memories = await asyncio.to_thread(
                self.memory_manager.search_memories, limit=self._batch_size, offset=offset
            )

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
                    from server.core.memory.decay import score_to_importance

                    new_importance = score_to_importance(decayed_value)

                    # H9: update_memory 对 metadata 是整列替换——必须先读旧
                    # metadata 合并衰减字段后再传全量，否则 {"importance_score",
                    # "decay_updated_at"} 两键覆写会清空 dream 的
                    # consolidation_state 等既有元数据（持续性数据丢失）。
                    # 快照条目来自 search_memories/_row_to_memory，metadata 已是
                    # 完整解析后的 dict。
                    merged_metadata = dict(memory.get("metadata") or {})
                    merged_metadata["importance_score"] = decayed_value
                    merged_metadata["decay_updated_at"] = datetime.now().isoformat()

                    success = await self.memory_manager.update_memory_async(
                        memory_id=memory_id,
                        new_importance=new_importance,
                        new_metadata=merged_metadata,
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
            sync_result = await asyncio.to_thread(self.memory_manager.sync_decay_values)
            logger.info(f"同步衰减值: 更新={sync_result['updated']}, 失败={sync_result['failed']}")

        return BatchDecayResult(
            total=len(memories), updated=updated_count, failed=failed_count, details=results
        )

    async def process_all(
        self, batch_size: int = 100, sync: bool = False, dry_run: bool = False
    ) -> Dict:
        """分批处理全部记忆直至取空，返回总批次、总更新/失败数与全部详情。"""
        total_updated = 0
        total_failed = 0
        all_details = []
        batch_count = 0

        # D3: 先取全量记忆快照（稳定遍历），再按切片处理——逐批 search(offset)
        # 会因更新 importance 改变 ORDER BY importance DESC 的排序位置而漏/重记忆。
        # R6: 快照为同步阻塞 IO，经 to_thread 卸载避免卡事件循环（对齐 L145 update_memory_async 模式）。
        snapshot = await asyncio.to_thread(self._snapshot_all_memories)
        if not snapshot:
            return {
                "total_batches": 0,
                "total_updated": 0,
                "total_failed": 0,
                "details": [],
            }

        offset = 0
        while offset < len(snapshot):
            batch_result = await self.process_batch(
                batch_size=batch_size,
                sync=False,
                dry_run=dry_run,
                offset=offset,
                memories=snapshot[offset: offset + batch_size],
            )

            batch_count += 1
            offset += batch_size
            total_updated += batch_result.updated
            total_failed += batch_result.failed
            all_details.extend(batch_result.details)

            logger.info(
                f"批次 {batch_count}: 总数={batch_result.total}, "
                f"更新={batch_result.updated}, 失败={batch_result.failed}"
            )

        if sync and not dry_run:
            sync_result = await asyncio.to_thread(self.memory_manager.sync_decay_values)
            logger.info(f"同步衰减值: 更新={sync_result['updated']}, 失败={sync_result['failed']}")

        return {
            "total_batches": batch_count,
            "total_updated": total_updated,
            "total_failed": total_failed,
            "details": all_details,
        }

    def _snapshot_all_memories(self) -> List[Dict]:
        """全量记忆快照（稳定遍历，不受 importance 排序位置变化影响）。"""
        memories: List[Dict] = []
        page = 1000
        offset = 0
        while True:
            batch = self.memory_manager.search_memories(limit=page, offset=offset)
            if not batch:
                break
            memories.extend(batch)
            if len(batch) < page:
                break
            offset += page
        return memories

    def get_batch_status(self) -> Dict:
        """返回当前批次大小、记忆管理器与衰减计算器的可用状态。"""
        return {
            "batch_size": self._batch_size,
            "memory_manager": self.memory_manager is not None,
            "decay_calculator": self.decay_calculator is not None,
        }
