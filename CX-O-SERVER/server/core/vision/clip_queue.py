"""主动视觉视频片段独立异步队列（VisionClipQueue）。

本模块是「路由 + 队列 + 临时清理」底座的核心载体，**不含任何视频理解消费逻辑**。

设计约束（对齐主动视觉视频叙事增强需求）：
1. **独立异步队列**：不复用对话 worker，避免与 <300ms 语音主链路争抢。
2. **可注入 consumer**：通过 ``set_consumer`` 注册真正的理解消费回调，
   供下游 VideoUnderstanding / 会话理解模块在未来接入。consumer 未设置时，
   队列仅做兜底临时清理，不执行任何理解动作。
3. **惰性启动**：首次 ``enqueue`` 时若 worker 未在运行，则惰性在调用方所在事件循环
   上 ``create_task`` 启动后台 ``_run`` 循环；无法获取运行中事件循环时安全失败返回 False。
4. **临时文件清理责任边界**：
   - **队列统一兜底**：对每个待办项，在 consumer 处理结束后的 ``finally`` 中删除
     ``clip_path``，保证「成功 / 超时 / 失败」均清理（幂等删除）。
   - consumer 也可自行删除/搬运 temp 文件（例如理解后转存正式目录），此时队列兜底
     因文件已不存在而跳过，不影响整体清理。**队列兜底保证不被遗漏**。

隐私红线：原始视频片段仅落临时区，由本队列终态清理，不落入正式目录。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

#: 队列中一个待处理条目的结构约定（下游 consumer 依此读取字段）
QUEUE_ITEM_KEYS = ("clip_path", "event_meta", "source", "ts", "accepted_at")


class VisionClipQueue:
    """独立异步视频片段处理队列（内存版）。

    Attributes:
        maxsize: ``asyncio.Queue`` 最大容量，超出时 ``enqueue`` 安全失败返回 False。
    """

    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._consumer: Optional[Callable] = None
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ #
    # 对外接口
    # ------------------------------------------------------------------ #
    def set_consumer(self, consumer: Optional[Callable]) -> None:
        """注册消费回调（下游 VideoUnderstanding / 会话理解接入点）。

        Args:
            consumer: 可等待回调 ``async consumer(item: Dict[str, Any])``；
                传 ``None`` 表示清空 consumer（仅保留队列兜底清理）。
        """
        self._consumer = consumer

    def enqueue(self, item: Dict[str, Any]) -> bool:
        """把一个片段条目放入队列并尽可能启动 worker。

        惰性启动：若 worker 尚未启动或已结束，则在「当前调用方所在事件循环」上
        创建后台 ``_run`` 任务。若当前无运行中的事件循环（如从纯同步线程调用），
        无法安全启动 worker，则安全失败返回 False。队列已满也返回 False。

        Args:
            item: 条目，至少含 ``clip_path``（见 ``QUEUE_ITEM_KEYS``）。

        Returns:
            bool: 入队成功返回 True；队列满 / 无法启动 worker / 异常返回 False。
        """
        try:
            if self._task is None or self._task.done():
                try:
                    asyncio.get_running_loop()
                except RuntimeError:
                    # 无运行中的事件循环：create_task 不可行（跨线程/不同 loop 会崩）
                    logger.warning(
                        "VisionClipQueue: 无运行中事件循环，无法惰性启动 worker，丢弃片段 %s",
                        item.get("clip_path"),
                    )
                    return False
                loop = asyncio.get_running_loop()
                self._task = loop.create_task(
                    self._run(), name="vision_clip_queue_worker"
                )
            self._queue.put_nowait(item)
            return True
        except asyncio.QueueFull:
            logger.warning("VisionClipQueue: 队列已满（%s），丢弃片段", item.get("clip_path"))
            return False
        except Exception as exc:  # noqa: BLE001 —— 面向外部调用者一律安全失败
            logger.warning("VisionClipQueue: 入队失败，丢弃片段: %s", exc)
            return False

    def pending_count(self) -> int:
        """当前队列中尚未取出的条目数。"""
        return self._queue.qsize()

    def is_ready(self) -> bool:
        """是否已注册 consumer（可字节消费）。"""
        return self._consumer is not None

    # ------------------------------------------------------------------ #
    # 内部 worker 循环
    # ------------------------------------------------------------------ #
    async def _run(self) -> None:
        """后台 worker：循环取条目 → 消费 → 兜底清理。

        异常兜底：consumer 异常会被捕获并记日志，worker 不崩溃，继续处理下一条。
        """
        while True:
            try:
                item = await self._queue.get()
            except asyncio.CancelledError:
                # worker 被取消（如服务关闭）——没有取出的条目不用清理
                raise
            try:
                consumer = self._consumer
                if consumer is None:
                    logger.warning("VisionClipQueue: 无 consumer，跳过片段跳过理解 %s", item.get("clip_path"))
                else:
                    await consumer(item)
            except asyncio.CancelledError:
                # consumer 被取消：仍需兜底清理，随后向上传播
                self._cleanup(item)
                self._queue.task_done()
                raise
            except Exception as exc:  # noqa: BLE001 —— consumer 失败不令 worker 崩溃
                logger.warning("VisionClipQueue: consumer 处理片段失败，已清理: %s", exc)
            finally:
                # 统一兜底：无论成功 / 超时 / 失败均清理临时文件（幂等）
                self._cleanup(item)
                self._queue.task_done()

    @staticmethod
    def _cleanup(item: Dict[str, Any]) -> None:
        """幂等删除条目的临时片段文件。consumer 也可自行删除，此处兜底保证终态清理。"""
        clip_path = item.get("clip_path")
        if not clip_path:
            return
        try:
            p = Path(clip_path)
            if p.exists():
                p.unlink()
                logger.info("VisionClipQueue: 已清理临时片段 %s", clip_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("VisionClipQueue: 清理临时片段失败 %s: %s", clip_path, exc)


#: 模块级单例 —— 路由与下游统一复用
vision_clip_queue = VisionClipQueue()