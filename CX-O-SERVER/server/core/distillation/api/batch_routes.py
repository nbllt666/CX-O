"""DistillationService v1.3.0 批量切分 + agent 创建路由。

5 个新增端点（与 public/interface_stub/distillation_service.pyi 扩展一致）:
    1. POST /api/v1/distillation/start-batch           — 批量切分启动蒸馏
    2. GET  /api/v1/distillation/group/{group_id}       — 查询批量切分组状态
    3. POST /api/v1/distillation/{session_id}/finalize-agent — 终结并创建角色卡 agent
    4. POST /api/v1/distillation/parse-character-card   — 解析 PNG/JSON 角色卡
    5. POST /api/v1/distillation/start-from-character-card — 从角色卡启动蒸馏

@version 1.4.0
"""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/v1/distillation", tags=["distillation-v1.3"])


class BatchStartRequest(BaseModel):
    """批量切分启动请求。"""

    source_type: str  # enum: text / character_card / image / conversation_log
    source_ref: str
    template_id: str
    max_turns: int = 4
    ask_user_on_ambiguity: bool = True
    chunk_size: int = 4000
    distillation_goal: str = "memory"  # enum: memory / agent / memory_and_agent
    target_agent_id: Optional[str] = None  # 记忆蒸馏注入的目标 agent


class FinalizeAgentRequest(BaseModel):
    """终结并创建 agent 请求。"""

    override_decision: Optional[str] = None


def _get_service(request: Request):
    """从 app.state 获取 DistillationService 实例。"""
    service = getattr(request.app.state, "distillation_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="DistillationService 未初始化（503）",
        )
    return service


@router.post(
    "/start-batch",
    summary="批量切分启动蒸馏",
    description="将超长 source_ref 切分为多个片段，每个片段创建独立 session，归属同一 session_group_id。",
)
async def start_batch_distillation(
    payload: BatchStartRequest,
    request: Request,
) -> Dict[str, Any]:
    """POST /api/v1/distillation/start-batch — 批量切分启动蒸馏。

    Args:
        payload: 批量启动请求
        request: FastAPI Request

    Returns:
        dict: session_group_id + sessions 数组 + total_chunks

    Raises:
        HTTPException: 422 (参数无效) / 500 (依赖服务不可用)
    """
    service = _get_service(request)
    try:
        return await service.start_batch_distillation(
            source_type=payload.source_type,
            source_ref=payload.source_ref,
            template_id=payload.template_id,
            max_turns=payload.max_turns,
            ask_user_on_ambiguity=payload.ask_user_on_ambiguity,
            chunk_size=payload.chunk_size,
            distillation_goal=payload.distillation_goal,
            target_agent_id=payload.target_agent_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/group/{group_id}",
    summary="查询批量切分组状态",
    description="返回同一 session_group_id 下所有 session 的状态。",
)
async def get_group_status(
    group_id: str,
    request: Request,
) -> Dict[str, Any]:
    """GET /api/v1/distillation/group/{group_id} — 查询批量切分组状态。

    Args:
        group_id: 会话组 ID
        request: FastAPI Request

    Returns:
        dict: group_id + sessions 状态数组 + completed_count + total_count

    Raises:
        HTTPException: 404 (group 不存在)
    """
    service = _get_service(request)
    try:
        return await service.get_group_status(group_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{session_id}/finalize-agent",
    summary="终结蒸馏并创建角色卡 agent",
    description="在 finalize 基础上，从 extracted_content 通过 LLM 提取角色卡 6 字段并创建 agent。",
)
async def finalize_with_agent_creation(
    session_id: str,
    payload: FinalizeAgentRequest,
    request: Request,
) -> Dict[str, Any]:
    """POST /api/v1/distillation/{session_id}/finalize-agent — 终结并创建 agent。

    Args:
        session_id: 会话 ID
        payload: 终结请求
        request: FastAPI Request

    Returns:
        dict: finalize 响应 + agent_creation_result

    Raises:
        HTTPException: 404 (session 不存在) / 409 (会话已终结) / 500 (agent 创建失败)
    """
    service = _get_service(request)
    try:
        return await service.finalize_with_agent_creation(
            session_id=session_id,
            override_decision=payload.override_decision,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"finalize_with_agent_creation 未捕获异常: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# v1.4.0 角色卡导入（PNG + JSON 解析 + 非标准字段支持）
# --------------------------------------------------------------------------- #


class StartFromCharacterCardRequest(BaseModel):
    """从角色卡启动蒸馏请求。"""

    character_card_data: Dict[str, Any]  # parse-character-card 返回的规范化数据
    template_id: str = "default"
    max_turns: int = 4
    ask_user_on_ambiguity: bool = False
    chunk_size: int = 4000
    distillation_goal: str = "memory_and_agent"  # 角色卡导入默认创建 agent


@router.post(
    "/parse-character-card",
    summary="解析 PNG/JSON 角色卡",
    description="解析 SillyTavern 角色卡（PNG tEXt chunk 或 JSON），返回规范化结构化数据。支持 V1/V2/V3 规范及非标准字段。",
)
async def parse_character_card(
    request: Request,
    file: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    """POST /api/v1/distillation/parse-character-card — 解析角色卡。

    支持两种输入方式：
    1. multipart/form-data: 上传 PNG/JSON 文件（字段名 file）
    2. application/json: 在 body 中传 json_content（需配合 Content-Type: application/json）

    PNG 文件通过 Pillow 读取 tEXt chunk，优先 V3（chara_card_v3），fallback V2（chara）。
    JSON 文件适配 V1（扁平化）、V2/V3（data 嵌套）。
    非标准字段保留到 extra_fields。

    Args:
        request: FastAPI Request
        file: 可选的文件上传（PNG 或 JSON）

    Returns:
        dict: 规范化角色卡数据 + source_ref（转换后的带标签文本）

    Raises:
        HTTPException: 400 (解析失败) / 422 (未提供文件)
    """
    from server.core.distillation.character_card_parser import (
        character_card_to_source_ref,
        parse_character_card_from_bytes,
        parse_character_card_from_json_str,
    )

    # 方式1: 文件上传
    if file is not None:
        try:
            file_bytes = await file.read()
            if not file_bytes:
                raise HTTPException(status_code=422, detail="上传文件为空")
            filename = file.filename or ""
            card_data = parse_character_card_from_bytes(file_bytes, filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception(f"角色卡文件解析未捕获异常: {exc}")
            raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc
    else:
        # 方式2: JSON body（json_content 字段）
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail="未提供文件且 body 不是有效 JSON。请上传文件或传 json_content",
            ) from exc

        json_content = body.get("json_content") if isinstance(body, dict) else None
        if not json_content:
            raise HTTPException(
                status_code=422,
                detail="未提供 file 且 body 中无 json_content 字段",
            )

        try:
            if isinstance(json_content, (dict, list)):
                # 已经是 dict/list，直接序列化后解析
                card_data = parse_character_card_from_json_str(
                    json.dumps(json_content, ensure_ascii=False)
                )
            else:
                card_data = parse_character_card_from_json_str(str(json_content))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception(f"角色卡 JSON 解析未捕获异常: {exc}")
            raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc

    # 生成 source_ref（带标签文本）
    source_ref = character_card_to_source_ref(card_data)

    return {
        "status": "success",
        "character_card_data": card_data,
        "source_ref": source_ref,
        "source_ref_length": len(source_ref),
    }


@router.post(
    "/start-from-character-card",
    summary="从角色卡启动蒸馏",
    description="将解析后的角色卡数据转换为带标签文本，启动批量蒸馏会话（source_type=character_card）。",
)
async def start_from_character_card(
    payload: StartFromCharacterCardRequest,
    request: Request,
) -> Dict[str, Any]:
    """POST /api/v1/distillation/start-from-character-card — 从角色卡启动蒸馏。

    将角色卡数据转换为 source_ref（带标签文本），调用 start_batch_distillation
    启动蒸馏会话。默认 distillation_goal=memory_and_agent（创建 agent + 注入记忆）。

    Args:
        payload: 请求体（角色卡数据 + 蒸馏参数）
        request: FastAPI Request

    Returns:
        dict: 批量蒸馏启动结果 + 角色卡数据

    Raises:
        HTTPException: 400 (角色卡数据无效) / 500 (蒸馏启动失败)
    """
    from server.core.distillation.character_card_parser import (
        character_card_to_source_ref,
    )

    card_data = payload.character_card_data
    if not isinstance(card_data, dict) or not card_data.get("name"):
        raise HTTPException(
            status_code=400,
            detail="character_card_data 无效或缺少 name 字段",
        )

    # 转换为 source_ref
    source_ref = character_card_to_source_ref(card_data)
    if not source_ref.strip():
        raise HTTPException(
            status_code=400,
            detail="角色卡转换为 source_ref 后为空（所有字段均为空）",
        )

    service = _get_service(request)
    try:
        batch_result = await service.start_batch_distillation(
            source_type="character_card",
            source_ref=source_ref,
            template_id=payload.template_id,
            max_turns=payload.max_turns,
            ask_user_on_ambiguity=payload.ask_user_on_ambiguity,
            chunk_size=payload.chunk_size,
            distillation_goal=payload.distillation_goal,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(f"start_from_character_card 蒸馏启动失败: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "success",
        "character_card_data": card_data,
        "distillation": batch_result,
    }
