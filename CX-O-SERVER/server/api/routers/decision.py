"""DecisionCore 决策路由（CX-O 迁移版 B4.4）。

挂接 RADIX-Lite DecisionCore 的 6 决策点 API 端点 + rejected_content 管理端点。

端点清单:
    - POST /api/decision/D1_LOCATION        决定存储位置
    - POST /api/decision/D2_METADATA         决定元数据
    - POST /api/decision/D3_ASK_USER         决定是否询问用户
    - POST /api/decision/D4_REDISTILL        决定是否重新蒸馏
    - POST /api/decision/D5_CROSS_VALIDATE   决定是否交叉验证
    - POST /api/decision/D6_REJECT           决定是否拒绝
    - GET  /api/decision/rejected/{session_id}  查询被拒绝内容
    - POST /api/decision/cleanup             清理过期被拒绝内容

对应契约:
    - 接口契约: public/interface_stub/decision_core.pyi
    - 数据契约: public/schema/storage_decision.schema.json
    - 数据契约: public/schema/rejected_content.schema.json

@version 1.0.0
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.core.decision.decision_core import (
    DecisionCore,
    DecisionInput,
    RubricSnapshot,
)
from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

# 模块级懒加载 DecisionCore 单例
_decision_core_instance: Optional[DecisionCore] = None


def _get_decision_core() -> DecisionCore:
    """懒加载 DecisionCore 实例（模块级单例）。"""
    global _decision_core_instance
    if _decision_core_instance is None:
        _decision_core_instance = DecisionCore()
    return _decision_core_instance


def _resolve_rubric(
    core: DecisionCore,
    agent_id: Optional[str],
    rubric_payload: Optional[Dict[str, Any]],
) -> RubricSnapshot:
    """解析 rubric：优先从 agents.json 加载（agent_id），否则用请求体 rubric。"""
    if agent_id:
        try:
            return core._load_rubric(agent_id)
        except (KeyError, IOError):
            # agent_id 加载失败时回退到请求体 rubric（若提供）
            if rubric_payload is None:
                raise
            logger.warning(
                f"agent_id={agent_id} rubric 加载失败，回退到请求体 rubric",
                exc_info=True,
            )
    if rubric_payload is None:
        raise ValueError("rubric 缺失：未提供 agent_id 且请求体无 rubric（422）")
    return RubricSnapshot(**rubric_payload)


def _map_decision_exception(exc: Exception) -> None:
    """将 DecisionCore 异常映射为 HTTP 异常。

    KeyError→404, ValueError→422, ConnectionError→503, RuntimeError→500。
    """
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ConnectionError):
        raise HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=500, detail=str(exc))
    raise HTTPException(status_code=500, detail=f"内部错误: {exc}")


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #


class DecisionInputModel(BaseModel):
    """决策输入（对应 decision_core.pyi DecisionInput）。"""
    artifact_summary: Optional[str] = None
    session_state: str
    turn_history_summary: Optional[str] = None
    extracted_content: Optional[str] = None
    quality_score: Optional[float] = None


class D1LocationRequest(BaseModel):
    """D1 存入位置决策请求。"""
    session_id: str
    decision_input: DecisionInputModel
    rubric: Optional[Dict[str, Any]] = None
    agent_id: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class D2MetadataRequest(BaseModel):
    """D2 元数据决策请求。"""
    session_id: str
    decision_input: DecisionInputModel


class D3AskUserRequest(BaseModel):
    """D3 追问决策请求。"""
    session_id: str
    llm_confidence: float
    rubric: Optional[Dict[str, Any]] = None
    agent_id: Optional[str] = None


class D4RedistillRequest(BaseModel):
    """D4 再次蒸馏决策请求。"""
    session_id: str
    current_turn: int
    rubric: Optional[Dict[str, Any]] = None
    agent_id: Optional[str] = None


class D5CrossValidateRequest(BaseModel):
    """D5 跨源验证决策请求。"""
    session_id: str
    decision_input: DecisionInputModel
    rubric: Optional[Dict[str, Any]] = None
    agent_id: Optional[str] = None


class D6RejectRequest(BaseModel):
    """D6 拒绝存储决策请求。"""
    session_id: str
    quality_score: float
    rubric: Optional[Dict[str, Any]] = None
    agent_id: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CleanupRequest(BaseModel):
    """清理过期被拒绝内容请求。"""
    retention_days: int = 30


# --------------------------------------------------------------------------- #
# 6 决策点端点
# --------------------------------------------------------------------------- #


@router.post("/decision/D1_LOCATION")
async def decide_location(request: D1LocationRequest, http_request: Request):
    """D1: 存入位置决策。

    根据 importance 和 rubric.importance_threshold_permanent 决定存入位置。
    若提供 content，则通过 memory_manager.write_with_decision 落库。
    """
    core = _get_decision_core()
    try:
        rubric = _resolve_rubric(core, request.agent_id, request.rubric)
        decision_input = DecisionInput(**request.decision_input.model_dump())
        decision = core.decide_location(
            session_id=request.session_id,
            decision_input=decision_input,
            rubric=rubric,
        )

        result: Dict[str, Any] = decision.model_dump()

        # 可选：通过 memory_manager 落库
        if request.content is not None:
            services = http_request.app.state.services
            mm = getattr(services, "memory_manager", None)
            if mm is not None and hasattr(mm, "write_with_decision"):
                write_result = mm.write_with_decision(
                    content=request.content,
                    decision=decision,
                    metadata=request.metadata,
                )
                result["write_result"] = write_result

        return result
    except HTTPException:
        raise
    except Exception as exc:
        _map_decision_exception(exc)


@router.post("/decision/D2_METADATA")
async def decide_metadata(request: D2MetadataRequest):
    """D2: 元数据决策。决定记忆的元数据（时间/重要性/来源/标签）。"""
    core = _get_decision_core()
    try:
        decision_input = DecisionInput(**request.decision_input.model_dump())
        metadata = core.decide_metadata(
            session_id=request.session_id,
            decision_input=decision_input,
        )
        return {"session_id": request.session_id, "metadata": metadata}
    except HTTPException:
        raise
    except Exception as exc:
        _map_decision_exception(exc)


@router.post("/decision/D3_ASK_USER")
async def decide_ask_user(request: D3AskUserRequest):
    """D3: 追问决策。根据 LLM 置信度决定是否追问人类。"""
    core = _get_decision_core()
    try:
        rubric = _resolve_rubric(core, request.agent_id, request.rubric)
        should_ask = core.decide_ask_user(
            session_id=request.session_id,
            llm_confidence=request.llm_confidence,
            rubric=rubric,
        )
        return {
            "session_id": request.session_id,
            "should_ask_user": should_ask,
            "llm_confidence": request.llm_confidence,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _map_decision_exception(exc)


@router.post("/decision/D4_REDISTILL")
async def decide_redistill(request: D4RedistillRequest):
    """D4: 再次蒸馏决策。根据当前轮次决定是否再次蒸馏。"""
    core = _get_decision_core()
    try:
        rubric = _resolve_rubric(core, request.agent_id, request.rubric)
        should_redistill = core.decide_redistill(
            session_id=request.session_id,
            current_turn=request.current_turn,
            rubric=rubric,
        )
        return {
            "session_id": request.session_id,
            "should_redistill": should_redistill,
            "current_turn": request.current_turn,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _map_decision_exception(exc)


@router.post("/decision/D5_CROSS_VALIDATE")
async def decide_cross_validate(request: D5CrossValidateRequest):
    """D5: 跨源验证决策。根据 rubric.cross_validate_sources 决定是否跨源验证。"""
    core = _get_decision_core()
    try:
        rubric = _resolve_rubric(core, request.agent_id, request.rubric)
        decision_input = DecisionInput(**request.decision_input.model_dump())
        should_validate = core.decide_cross_validate(
            session_id=request.session_id,
            decision_input=decision_input,
            rubric=rubric,
        )
        return {
            "session_id": request.session_id,
            "should_cross_validate": should_validate,
        }
    except HTTPException:
        raise
    except Exception as exc:
        _map_decision_exception(exc)


@router.post("/decision/D6_REJECT")
async def decide_reject(request: D6RejectRequest, http_request: Request):
    """D6: 拒绝存储决策。质量分过低时拒绝入库。

    若提供 content，则通过 memory_manager.write_with_decision 写入 rejected_content 表。
    """
    core = _get_decision_core()
    try:
        rubric = _resolve_rubric(core, request.agent_id, request.rubric)
        decision = core.decide_reject(
            session_id=request.session_id,
            quality_score=request.quality_score,
            rubric=rubric,
        )

        result: Dict[str, Any] = decision.model_dump()

        # 可选：通过 memory_manager 写入 rejected_content 表
        if request.content is not None:
            services = http_request.app.state.services
            mm = getattr(services, "memory_manager", None)
            if mm is not None and hasattr(mm, "write_with_decision"):
                write_result = mm.write_with_decision(
                    content=request.content,
                    decision=decision,
                    metadata=request.metadata,
                )
                result["write_result"] = write_result

        return result
    except HTTPException:
        raise
    except Exception as exc:
        _map_decision_exception(exc)


# --------------------------------------------------------------------------- #
# rejected_content 管理端点（B4.3 3 方法的 HTTP 暴露）
# --------------------------------------------------------------------------- #


@router.get("/decision/rejected/{session_id}")
async def get_rejected_content(session_id: str, http_request: Request, limit: int = 50):
    """查询指定会话的被拒绝内容。"""
    services = http_request.app.state.services
    mm = getattr(services, "memory_manager", None)
    if mm is None or not hasattr(mm, "get_rejected_content"):
        raise HTTPException(status_code=503, detail="memory_manager 不可用或未集成 decision mixin")
    try:
        records = mm.get_rejected_content(session_id=session_id, limit=limit)
        return {"session_id": session_id, "count": len(records), "records": records}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/decision/cleanup")
async def cleanup_expired_rejected_content(request: CleanupRequest, http_request: Request):
    """清理过期的被拒绝内容（标记 is_purged=True）。"""
    services = http_request.app.state.services
    mm = getattr(services, "memory_manager", None)
    if mm is None or not hasattr(mm, "cleanup_expired_rejected_content"):
        raise HTTPException(status_code=503, detail="memory_manager 不可用或未集成 decision mixin")
    try:
        purged_count = mm.cleanup_expired_rejected_content(
            retention_days=request.retention_days
        )
        return {"purged_count": purged_count, "retention_days": request.retention_days}
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
