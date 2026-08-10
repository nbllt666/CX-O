"""DistillationService FastAPI 路由定义。

4 个 REST API 端点（与 public/interface_stub/distillation_service.pyi 一致）:
    1. POST /api/v1/distillation/start                      — 启动蒸馏会话
    2. POST /api/v1/distillation/{session_id}/advance       — 推进蒸馏状态机
    3. POST /api/v1/distillation/{session_id}/finalize      — 终结蒸馏会话
    4. GET  /api/v1/distillation/{session_id}               — 查询会话状态

异常映射（与 distillation_session.schema.json definitions.exceptions 一致）:
    - start:     ValueError → 422, RuntimeError → 422, ConnectionError → 500
    - advance:   KeyError → 404, ValueError → 409, RuntimeError → 500
    - finalize:  KeyError → 404, ValueError → 409, RuntimeError → 500
    - get:       KeyError → 404

@version 1.0.0
"""

from fastapi import APIRouter, HTTPException, Request

from server.core.distillation.distillation_service import (
    AdvanceDistillationRequest,
    AdvanceDistillationResponse,
    FinalizeDistillationRequest,
    FinalizeDistillationResponse,
    SessionStatusResponse,
    StartDistillationRequest,
    StartDistillationResponse,
)


# --------------------------------------------------------------------------- #
# 路由器构造
# --------------------------------------------------------------------------- #

router = APIRouter(prefix="/api/v1/distillation", tags=["distillation"])


def _get_service(request: Request):
    """从 app.state 获取 DistillationService 实例。

    Args:
        request: FastAPI Request 对象

    Returns:
        DistillationService 实例

    Raises:
        HTTPException: 服务未初始化（500）
    """
    service = getattr(request.app.state, "distillation_service", None)
    if service is None:
        raise HTTPException(
            status_code=500,
            detail="DistillationService 未初始化（500）",
        )
    return service


# --------------------------------------------------------------------------- #
# 4 个 API 端点
# --------------------------------------------------------------------------- #


@router.post(
    "/start",
    response_model=StartDistillationResponse,
    summary="启动蒸馏会话",
    description="异步触发 MultimodalPipeline 预处理，session 进入 S_PREREAD 状态。",
)
async def start_distillation(
    payload: StartDistillationRequest,
    request: Request,
) -> StartDistillationResponse:
    """POST /api/v1/distillation/start — 启动蒸馏会话。

    Args:
        payload: 启动请求（source_type / source_ref / template_id / max_turns / ask_user_on_ambiguity）
        request: FastAPI Request

    Returns:
        StartDistillationResponse: session_id + initial_state + preread_summary

    Raises:
        HTTPException: 422 (参数无效) / 500 (依赖服务不可用)
    """
    service = _get_service(request)
    try:
        return await service.start_distillation(
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            template_id=payload.template_id,
            max_turns=payload.max_turns,
            ask_user_on_ambiguity=payload.ask_user_on_ambiguity,
        )
    except ValueError as exc:
        # source_type 不在枚举 / max_turns 超范围 / template_id 为空（422）
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        # MultimodalPipeline 预处理失败（422）
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConnectionError as exc:
        # MultimodalPipeline 不可用（500）
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/{session_id}/advance",
    response_model=AdvanceDistillationResponse,
    summary="推进蒸馏状态机",
    description="推进状态机一步，支持回环（S_REFLECT → S_QUESTION）和主动追问。",
)
async def advance_distillation(
    session_id: str,
    payload: AdvanceDistillationRequest,
    request: Request,
) -> AdvanceDistillationResponse:
    """POST /api/v1/distillation/{session_id}/advance — 推进蒸馏状态机。

    Args:
        session_id: 会话 ID
        payload: 推进请求（user_response）
        request: FastAPI Request

    Returns:
        AdvanceDistillationResponse: session_id + current_state + agent_action + next_needed

    Raises:
        HTTPException: 404 (session 不存在) / 409 (状态冲突) / 500 (LLM 调用失败)
    """
    service = _get_service(request)
    try:
        return await service.advance_distillation(
            session_id=session_id,
            user_response=payload.user_response,
        )
    except KeyError as exc:
        # session_id 不存在（404）
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # 非法状态转移 / 会话已终结 / 超过最大轮次（409）
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        # LLM 调用失败（500）
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/{session_id}/finalize",
    response_model=FinalizeDistillationResponse,
    summary="终结蒸馏会话",
    description="执行存储决策，调用 DecisionCore 6 决策点。",
)
async def finalize_distillation(
    session_id: str,
    payload: FinalizeDistillationRequest,
    request: Request,
) -> FinalizeDistillationResponse:
    """POST /api/v1/distillation/{session_id}/finalize — 终结蒸馏会话。

    Args:
        session_id: 会话 ID
        payload: 终结请求（override_decision）
        request: FastAPI Request

    Returns:
        FinalizeDistillationResponse: stored + location + memory_id + metadata + reason

    Raises:
        HTTPException: 404 (session 不存在) / 409 (会话已终结) / 500 (DecisionCore 失败)
    """
    service = _get_service(request)
    try:
        return await service.finalize_distillation(
            session_id=session_id,
            override_decision=payload.override_decision,
        )
    except KeyError as exc:
        # session_id 不存在（404）
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # 会话已终结（409）
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        # DecisionCore 决策失败 / 审计日志写入失败（500）
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{session_id}",
    response_model=SessionStatusResponse,
    summary="查询会话状态",
    description="返回完整会话状态，字段与 distillation_session.schema.json 一致。",
)
async def get_session_status(
    session_id: str,
    request: Request,
) -> SessionStatusResponse:
    """GET /api/v1/distillation/{session_id} — 查询会话状态。

    Args:
        session_id: 会话 ID
        request: FastAPI Request

    Returns:
        SessionStatusResponse: 完整会话状态

    Raises:
        HTTPException: 404 (session 不存在)
    """
    service = _get_service(request)
    try:
        return await service.get_session_status(session_id=session_id)
    except KeyError as exc:
        # session_id 不存在（404）
        raise HTTPException(status_code=404, detail=str(exc)) from exc
