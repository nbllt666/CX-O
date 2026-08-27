"""主动视觉生产装配 —— 把队列接到理解 + 叙事沉淀链（Task 12・GN-004 阻断修正）。

职责（仅装配，不含理解/沉淀实现，不重造轮子）：
    本模块是「生产链接线」的唯一装配点：读取 ``vision_enhanced.enabled``，
    为 True 时实例化 ``VideoUnderstanding`` 注册为 ``vision_clip_queue`` 的
    consumer，并在 consumer 产出 ``NarrativeSummary`` 后调用
    ``NarrativeVisionMemory.sediment_from_consumer`` 完成 ``source='vision'`` 落库。

解决 GN-004 阻断项 12.1：此前 ``VideoUnderstanding.register_as_consumer`` 与
``sediment_from_consumer`` 仅在 tests/ 被调用，上传 clip 在队列 ``_run`` 中因
``consumer is None`` 被静默丢弃，``source='vision'`` 记忆永不产生。本装配把
该调用链接进服务启动生命周期（见 ``server/main.py`` lifespan 中的 init_service）。

设计约束（rules-0 §三 sorting / 渐进式生成 / 幂等）:
    - **可显式调用**：``register_vision_pipeline`` 不依赖 FastAPI lifespan，可被
      启动装配或测试直接调用，便于独立触发且不污染既有启动测试。
    - **可注入组件**：``queue``/``understanding``/``memory`` 可注入（测试用替身），
      缺省懒加载生产实例。**生产装配默认路径用真实组件，不依赖测试 mock**。
    - **幂等**：按 ``id(queue)`` 记录已注册队列，重复调用不重复 ``set_consumer``，
      兼容 app reload / 多次启动。
    - **enabled=false 不注册**：为 False 直接返回 False，consumer 保持 None，
      上传 clip 仍走「未启用忽略」原语义。
    - **异常不崩 worker**：consumer 外包 try/except，理解/沉淀失败仅记日志，
      worker 继续处理后续条目（与 ``VisionClipQueue._run`` 兜底语义一致）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from server.config import get_settings
from server.core.vision.clip_queue import VisionClipQueue, vision_clip_queue

logger = logging.getLogger(__name__)

#: 已注册生产 consumer 的队列 id 集合（防 app 重载 / 多次调用重复注册；测试可重置）
_REGISTERED_QUEUES: set = set()


def _wrap_consumer(understanding: Any, memory: Any):
    """把「理解 → 沉淀」串成队列 consumer（异常隔离，worker 不崩）。

    Args:
        understanding: 队列 consumer，具 ``async consume(item) -> NarrativeSummary | None``。
        memory: 叙事记忆沉淀器，具 ``sediment_from_consumer(item, summary)``。

    Returns:
        ``async consumer(item)`` 回调，供 ``VisionClipQueue.set_consumer`` 使用。
    """

    async def consumer(item: Dict[str, Any]) -> None:
        try:
            summary = await understanding.consume(item)
        except Exception as exc:  # noqa: BLE001 —— 理解失败不崩 worker（队列会兜底清理）
            logger.warning("VisionPipeline: 理解片段失败，跳过沉淀: %s", exc)
            return
        if summary is None:
            return
        try:
            # 沉淀链内部含同步 LLM 决策（DecisionCore D1 requests.post）与记忆落库，
            # 直接 await 会阻塞事件循环（F1 修复）：整体卸载到 IO 线程执行。
            await asyncio.to_thread(memory.sediment_from_consumer, item, summary)
        except Exception as exc:  # noqa: BLE001 —— 沉淀失败不崩 worker
            logger.warning("VisionPipeline: 沉淀叙事记忆失败（不阻断 worker）: %s", exc)

    return consumer


def register_vision_pipeline(
    queue: Optional[VisionClipQueue] = None,
    understanding: Any = None,
    memory: Any = None,
) -> bool:
    """把主动视觉队列接到生产理解 + 叙事沉淀链（幂等）。

    Args:
        queue: 目标队列，缺省模块级单例 ``vision_clip_queue``。
        understanding: 理解组件（队列 consumer），缺省懒加载 ``VideoUnderstanding()``。
        memory: 叙事记忆沉淀器，缺省懒加载 ``NarrativeVisionMemory()``。

    Returns:
        bool:
            - ``vision_enhanced.enabled`` 为 False → False（不注册）。
            - 目标队列已注册（幂等）→ True（不重复 ``set_consumer``）。
            - 首次成功装配 → True。
            - 装配异常（配置读取失败等）→ False 并记告警（不阻断服务启动）。
    """
    target = queue if queue is not None else vision_clip_queue
    try:
        ve = get_settings().config.vision_enhanced
        if not getattr(ve, "enabled", False):
            logger.info("VisionPipeline: vision_enhanced 未启用，跳过生产接线")
            return False

        qid = id(target)
        if qid in _REGISTERED_QUEUES:
            logger.info("VisionPipeline: 队列已注册 consumer（幂等），跳过")
            return True

        if understanding is None:
            from server.core.vision.video_understanding import VideoUnderstanding

            understanding = VideoUnderstanding()
        if memory is None:
            from server.core.vision.narrative_memory import NarrativeVisionMemory

            memory = NarrativeVisionMemory()

        target.set_consumer(_wrap_consumer(understanding, memory))
        _REGISTERED_QUEUES.add(qid)
        logger.info("VisionPipeline: 主动视觉生产链已接线（consumer 已注册）")
        return True
    except Exception as exc:  # noqa: BLE001 —— 装配失败仅告警，不阻断启动
        logger.warning("VisionPipeline: 生产装配失败，已隔离: %s", exc)
        return False


__all__ = [
    "register_vision_pipeline",
    "_REGISTERED_QUEUES",
]