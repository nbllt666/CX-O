"""CX-O-Autonomy 反思层·经历整合器（P1-T7）。

Consolidator 对多条自主经历做整合/蒸馏：当注入可调用的 distillation_provider
时把 entries 交由其处理并返回结果；否则返回轻量占位统计
{"consolidated": len(entries), "distilled": False}。

P3-T2 接入真实蒸馏服务：
- distillation_provider 注入点保持向后兼容（签名 (entries) -> dict，可同步/异步）；
- 另新增 distillation_service 注入点——当真实 DistillationService 实例经
  services 注入时，直接调用其 start_distillation / finalize_distillation 完成
  蒸馏闭环（见 distill_via_service）；未注入时保持现有占位返回。
- 蒸馏路径为 best-effort：服务调用异常被捕获记录日志，返回降级结果
  {"consolidated": N, "distilled": False, "error": ...}，不向上冒泡。

本模块无文件 IO，禁止相对路径。
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)

# 蒸馏会话默认参数（对齐 distillation_service.pyi / distillation_session.schema.json）
_DISTILL_SOURCE_TYPE = "text"  # 自主经历整合统一走 text 模态
_DISTILL_TEMPLATE_ID = "autonomy_consolidation"
_DISTILL_MAX_TURNS = 1
_DISTILL_ASK_USER = False


class Consolidator:
    """自主经历整合器：可选蒸馏服务接入点。

    Args:
        distillation_provider: 蒸馏服务回调，签名 (entries) -> dict，可同步或异步；
            为 None 或不可调用时走占位统计路径。
        distillation_service: 真实 DistillationService 实例（可选）；非 None 且
            暴露 start_distillation / finalize_distillation 时优先走直接调用路径
            （distill_via_service），否则回退 provider / 占位统计。
    """

    def __init__(
        self,
        distillation_provider: Optional[Callable] = None,
        distillation_service: Optional[Any] = None,
    ) -> None:
        """初始化整合器：保存蒸馏服务回调与真实蒸馏服务实例。"""
        self.distillation_provider: Optional[Callable] = distillation_provider
        self.distillation_service: Optional[Any] = distillation_service

    def _service_usable(self) -> bool:
        """蒸馏服务实例是否可被直接调用（start_distillation + finalize_distillation 均存在）。"""
        svc = self.distillation_service
        return bool(
            svc is not None
            and callable(getattr(svc, "start_distillation", None))
            and callable(getattr(svc, "finalize_distillation", None))
        )

    async def consolidate(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """整合给定经历列表。

        优先级：
            1. 注入可用的 distillation_service 实例 → distill_via_service（真实蒸馏闭环）
            2. 注入可调用 distillation_provider → 返回其调用结果
            3. 否则返回 {"consolidated": len(entries), "distilled": False}

        Args:
            entries: 经历条目列表（dict）

        Returns:
            dict：整合结果。蒸馏服务调用失败时返回降级结果，不冒泡。
        """
        if self._service_usable():
            try:
                return await self.distill_via_service(entries)
            except Exception as e:  # noqa: BLE001
                logger.error("蒸馏服务整合经历失败（不冒泡）: %s", e)
                return {
                    "consolidated": len(entries),
                    "distilled": False,
                    "error": str(e),
                }

        provider = self.distillation_provider
        if provider is not None and callable(provider):
            result = provider(entries)
            if inspect.isawaitable(result):
                result = await result
            return result
        return {"consolidated": len(entries), "distilled": False}

    async def distill_via_service(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """直接调用真实蒸馏服务完成整合（start → finalize）。

        把经历列表序列化为 text 源（source_ref）启动一个蒸馏会话，随后终结该会话
        执行存储决策。调用约定对齐 distillation_service.pyi：
            start_distillation(source_type, source_ref, template_id, max_turns,
                               ask_user_on_ambiguity) -> StartDistillationResponse
            finalize_distillation(session_id, override_decision) -> FinalizeDistillationResponse

        Args:
            entries: 经历条目列表（dict）

        Returns:
            dict：蒸馏整合结果，含 session_id / distilled / finalized / location /
                memory_id / metadata / reason。异常由调用方（consolidate）捕获降级。
        """
        svc = self.distillation_service
        source_ref = (
            json.dumps(entries, ensure_ascii=False, default=str) if entries else ""
        )
        start = await svc.start_distillation(
            source_type=_DISTILL_SOURCE_TYPE,
            source_ref=source_ref,
            template_id=_DISTILL_TEMPLATE_ID,
            max_turns=_DISTILL_MAX_TURNS,
            ask_user_on_ambiguity=_DISTILL_ASK_USER,
        )
        session_id = str(getattr(start, "session_id", ""))
        final = await svc.finalize_distillation(
            session_id=session_id, override_decision=None
        )
        return {
            "distilled": True,
            "session_id": session_id,
            "finalized": bool(getattr(final, "stored", False)),
            "location": getattr(final, "location", None),
            "memory_id": getattr(final, "memory_id", None),
            "metadata": getattr(final, "metadata", {}),
            "reason": getattr(final, "reason", ""),
        }
