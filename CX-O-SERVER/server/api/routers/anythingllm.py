"""AnythingLLM 兼容 API 路由模块。

迁移自 CXHMS backend/api/routers/anythingllm.py（适配 CX-O 路径与配置风格）。

提供 AnythingLLM Developer API 兼容端点，使支持 AnythingLLM API 的工具/客户端可直接对接 CX-O。

Phase 1 端点（11个）：
  认证: GET /v1/auth
  OpenAI 兼容: GET /v1/openai/models, POST /v1/openai/chat/completions
  Workspace 管理: GET /v1/workspaces, POST /v1/workspace/new, GET/POST/DELETE /v1/workspace/{slug}*
  Workspace 聊天: POST /v1/workspace/{slug}/chat, POST /v1/workspace/{slug}/stream-chat, GET /v1/workspace/{slug}/chats

Phase 2 端点（7个 Document）：
  文档上传: POST /v1/document/upload, POST /v1/document/raw-text
  文档查询: GET /v1/documents, GET /v1/document/{docName}
  文档删除: DELETE /v1/document/{docName}
  Workspace 文档关联: POST /v1/workspace/{slug}/update-embeddings
  元数据 schema: GET /v1/document/metadata-schema
"""

import hmac
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.api.routers.agents import _load_agents, _save_agents
from server.chat_helpers import ensure_agent_session, get_llm_client_for_agent
from server.core.logging_config import get_contextual_logger
from server.dependencies import get_document_memory_manager

router = APIRouter()
logger = get_contextual_logger(__name__)

# CX-O 适配：API key 通过环境变量配置（与 admin.py 风格一致）
# 未设置环境变量时，API 完全开放（开发模式）；设置后要求 Bearer token 匹配
ANYTHINGLLM_API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "")


# ========== 认证依赖 ==========

async def verify_api_key(authorization: Optional[str] = Header(None)) -> None:
    """验证 Bearer token 认证。

    CX-O 适配：
    - ANYTHINGLLM_API_KEY 环境变量未设置 → 直接放行（开发模式）
    - 已设置 → 校验 Authorization: Bearer <token>

    Args:
        authorization: Authorization header 值，格式 "Bearer <token>"

    Raises:
        HTTPException(401): token 不匹配或缺失（当 API key 已配置时）
    """
    if not ANYTHINGLLM_API_KEY:
        return

    if not authorization:
        raise HTTPException(status_code=401, detail={"error": "Invalid API Key"})

    # 解析 Bearer token
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"error": "Invalid API Key"})

    token = authorization[7:]  # 去掉 "Bearer " 前缀
    if not hmac.compare_digest(token, ANYTHINGLLM_API_KEY):
        raise HTTPException(status_code=401, detail={"error": "Invalid API Key"})


# ========== 请求/响应模型 ==========

class OpenAIChatRequest(BaseModel):
    """OpenAI Chat Completions 请求格式。"""
    model: str = "main"
    messages: List[Dict[str, Any]]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class WorkspaceChatRequest(BaseModel):
    """AnythingLLM workspace chat 请求格式。"""
    message: str
    mode: str = "chat"  # chat | query | automatic
    sessionId: Optional[str] = None  # 接受但不使用
    attachments: Optional[List[Dict[str, Any]]] = None
    reset: bool = False


class WorkspaceCreateRequest(BaseModel):
    """创建 workspace 请求。"""
    name: str


class WorkspaceUpdateRequest(BaseModel):
    """更新 workspace 请求。"""
    name: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


# Phase 2 请求模型

class RawTextRequest(BaseModel):
    """文本上传请求。"""
    textContent: str
    metadata: Dict[str, Any] = {}
    addToWorkspaces: Optional[str] = None


class UpdateEmbeddingsRequest(BaseModel):
    """workspace 文档关联请求。"""
    adds: List[str] = []
    deletes: List[str] = []


# ========== 工具函数 ==========

def _agent_to_workspace(agent: Dict[str, Any]) -> Dict[str, Any]:
    """将 CX-O agent 映射为 AnythingLLM workspace。"""
    return {
        "id": agent.get("id"),
        "name": agent.get("name", ""),
        "slug": agent.get("id"),  # slug = agent_id
        "createdAt": agent.get("created_at", datetime.now().isoformat()),
    }


def _agent_to_workspace_detail(agent: Dict[str, Any]) -> Dict[str, Any]:
    """将 CX-O agent 映射为 AnythingLLM workspace 详情（含 settings）。"""
    ws = _agent_to_workspace(agent)
    ws["settings"] = {
        "model": agent.get("model", "main"),
        "temperature": agent.get("temperature", 0.7),
        "system_prompt": agent.get("system_prompt", ""),
    }
    ws["embedCount"] = 0
    return ws


def _find_agent_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """通过 slug（= agent_id）查找 agent。"""
    agents = _load_agents()
    return next((a for a in agents if a.get("id") == slug), None)


def _get_model_list() -> List[Dict[str, Any]]:
    """获取可用模型列表（model_router 模型 + agent:* 条目）。"""
    models = []

    # 从 model_router 获取已配置的模型
    try:
        from server.dependencies import get_model_router
        model_router = get_model_router()
        if model_router and hasattr(model_router, "_clients"):
            for model_type, client in model_router._clients.items():
                if hasattr(client, "model") and client.model:
                    models.append({
                        "id": client.model,
                        "object": "model",
                        "owned_by": "cx-o",
                    })
    except Exception as e:
        logger.warning(f"从 model_router 获取模型列表失败: {e}")

    # 添加 agent:* 格式的 agent 列表
    try:
        agents = _load_agents()
        for agent in agents:
            models.append({
                "id": f"agent:{agent['id']}",
                "object": "model",
                "owned_by": "cx-o",
            })
    except Exception as e:
        logger.warning(f"获取 agent 列表失败: {e}")

    return models


def _parse_model_field(model: str) -> tuple[Optional[Dict[str, Any]], str]:
    """解析 model 字段，返回 (agent_config, actual_model)。

    model 格式：
    - "agent:<id>" → 使用指定 agent 配置，actual_model = agent 的 model
    - 普通模型名 → 使用默认 agent 配置，actual_model = model
    """
    if model.startswith("agent:"):
        agent_id = model[6:]
        agent_config = _find_agent_by_slug(agent_id)
        if not agent_config:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' 不存在")
        return agent_config, agent_config.get("model", "main")
    else:
        # 使用默认 agent 配置 + 指定模型
        agent_config = _find_agent_by_slug("default")
        if not agent_config:
            # 回退：使用最小配置
            agent_config = {
                "id": "default",
                "name": "默认助手",
                "system_prompt": "你是一个有帮助的AI助手。",
                "model": model,
                "temperature": 0.7,
                "max_tokens": 4096,
                "use_memory": False,
                "use_tools": False,
            }
        else:
            agent_config = {**agent_config, "model": model}
        return agent_config, model


def _build_messages_for_chat(
    agent_config: Dict[str, Any],
    user_message: str,
    history: Optional[List[Dict]] = None,
) -> List[Dict[str, str]]:
    """构建 LLM 消息列表（AnythingLLM 兼容路径：统一入口，保持最小化行为）。"""
    from server.prompt_builder import build_messages

    return build_messages(
        agent_config,
        context_mgr=None,
        session_id=None,
        user_message=user_message,
        history=history if history else None,
        include_hidden_prompts=False,  # 兼容路径不注入重型隐藏提示词
    )


def _get_or_create_session(context_mgr, slug: str, agent_config: Dict[str, Any]) -> str:
    """获取或创建 workspace 对应的会话。"""
    return ensure_agent_session(context_mgr, slug, agent_config.get("name", slug))


def _save_chat_message(context_mgr, session_id: str, role: str, content: str) -> None:
    """保存聊天消息到 context_manager（同步，非阻塞主流程）。"""
    try:
        context_mgr.add_message(
            session_id=session_id,
            role=role,
            content=content,
            content_type="text",
        )
    except Exception as e:
        logger.warning(f"保存聊天消息失败（不影响主流程）: {e}")


def _process_attachments(attachments: Optional[List[Dict[str, Any]]]) -> tuple[str, List[str]]:
    """处理附件，返回 (文档文本, 图片URL列表)。

    文档附件解析为文本，拼接到用户消息前；图片附件直接传递给 LLM。
    """
    if not attachments:
        return "", []

    try:
        from server.core.document.parser import parse_attachments
        return parse_attachments(attachments)
    except Exception as e:
        logger.warning(f"附件解析失败（不影响主流程）: {e}")
        return f"[附件解析失败: {e}]", []


def _prepare_chat_context(slug: str, request: WorkspaceChatRequest, agent: Dict[str, Any]):
    """准备聊天上下文（chat 和 stream-chat 的公共逻辑）。

    处理：会话管理、reset、mode 区分、attachments、消息构建。

    Args:
        slug: workspace slug（= agent_id）
        request: WorkspaceChatRequest 请求体
        agent: agent 配置

    Returns:
        (context_mgr, session_id, messages, kwargs): 上下文管理器、会话ID（query 模式为 None）、
        消息列表、LLM 调用 kwargs
    """
    from server.dependencies import get_context_manager
    context_mgr = get_context_manager()

    session_id = None
    history = []

    if context_mgr and request.mode != "query":
        # chat/automatic 模式：使用历史
        session_id = _get_or_create_session(context_mgr, slug, agent)

        # reset: 清空会话历史
        if request.reset:
            context_mgr.clear_session_messages(session_id)
            logger.info(f"会话 {session_id} 历史已清空（reset=true）")
        else:
            # 加载历史
            history = context_mgr.get_recent_messages(session_id, limit=50)

    # 处理附件
    doc_text, image_urls = _process_attachments(request.attachments)

    # 构建用户消息（附件文档文本拼接到消息前）
    user_message = request.message
    if doc_text:
        user_message = f"以下是附件文档内容，请参考：\n\n{doc_text}\n\n用户问题：{request.message}"

    # 构建消息列表
    messages = _build_messages_for_chat(agent, user_message, history if history else None)

    # 构建 kwargs（图片附件）
    kwargs = {}
    if image_urls and agent.get("vision_enabled", False):
        kwargs["images"] = image_urls

    return context_mgr, session_id, messages, kwargs


def _persist_chat(context_mgr, session_id: Optional[str], user_message: str, assistant_response: str) -> None:
    """持久化聊天消息到 context_manager（chat 和 stream-chat 的公共逻辑）。"""
    if not session_id or not context_mgr:
        return
    _save_chat_message(context_mgr, session_id, "user", user_message)
    _save_chat_message(context_mgr, session_id, "assistant", assistant_response)


def _doc_row_to_response(row: Dict[str, Any], include_text: bool = False) -> Dict[str, Any]:
    """将 documents 表行转换为响应字典。"""
    resp = {
        "doc_name": row.get("doc_name"),
        "title": row.get("title"),
        "doc_author": row.get("doc_author", "Unknown"),
        "description": row.get("description", "Unknown"),
        "doc_source": row.get("doc_source"),
        "mime_type": row.get("mime_type"),
        "word_count": row.get("word_count", 0),
        "token_count_estimate": row.get("token_count_estimate", 0),
        "text_content": row.get("text_content") if include_text else None,
        "memory_id": row.get("memory_id"),
        "folder": row.get("folder", "custom-documents"),
        "file_path": row.get("file_path"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "is_deleted": bool(row.get("is_deleted", False)),
    }
    # 详情接口可能附带 workspace 关联字段
    if "is_pinned" in row:
        resp["is_pinned"] = bool(row.get("is_pinned", False))
    if "associated_at" in row:
        resp["associated_at"] = row.get("associated_at")
    return resp


# ========== 端点实现 ==========

# --- Phase 1: 认证端点 ---

@router.get("/v1/auth")
async def auth(authorization: Optional[str] = Header(None)):
    """GET /v1/auth — 验证 API token。"""
    await verify_api_key(authorization)
    return {"authenticated": True}


# --- Phase 1: 模型列表 ---

@router.get("/v1/openai/models")
async def list_models(authorization: Optional[str] = Header(None)):
    """GET /v1/openai/models — 列出可用模型。"""
    await verify_api_key(authorization)
    models = _get_model_list()
    return {"object": "list", "data": models}


# --- Phase 1: OpenAI 兼容聊天补全 ---

@router.post("/v1/openai/chat/completions")
async def chat_completions(request: OpenAIChatRequest, authorization: Optional[str] = Header(None)):
    """POST /v1/openai/chat/completions — OpenAI 兼容聊天补全。"""
    await verify_api_key(authorization)

    # 解析 model 字段
    agent_config, actual_model = _parse_model_field(request.model)

    # 获取 LLM 客户端
    llm = get_llm_client_for_agent(agent_config)
    if not llm:
        raise HTTPException(status_code=500, detail="LLM 客户端不可用")

    # 构建消息（直接使用请求中的 messages）
    messages = request.messages

    # 构建 kwargs
    kwargs = {}
    if request.temperature is not None:
        kwargs["temperature"] = request.temperature
    if request.max_tokens is not None:
        kwargs["max_tokens"] = request.max_tokens

    chatcmpl_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if request.stream:
        # 流式响应
        async def stream_generator():
            try:
                async for chunk in llm.stream_chat(messages, **kwargs):
                    if chunk.get("type") == "content":
                        delta = {"content": chunk["content"]}
                        chunk_data = {
                            "id": chatcmpl_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": actual_model,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk_data, ensure_ascii=False)}\n\n"
                    elif chunk.get("type") == "error":
                        logger.error(f"LLM 流式错误: {chunk.get('content')}")
                        break
                # 末尾 [DONE]
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"流式聊天失败: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        # 非流式响应
        try:
            response = await llm.chat(messages, stream=False, **kwargs)
            content = response.content or ""
            finish_reason = response.finish_reason or "stop"
            usage = response.usage or {}

            # 构造 OpenAI ChatCompletion 响应
            return {
                "id": chatcmpl_id,
                "object": "chat.completion",
                "created": created,
                "model": actual_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
            }
        except Exception as e:
            logger.error(f"非流式聊天失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"LLM 调用失败: {str(e)}")


# --- Phase 1: Workspace 管理 ---

@router.get("/v1/workspaces")
async def list_workspaces(authorization: Optional[str] = Header(None)):
    """GET /v1/workspaces — 列出所有 workspace。"""
    await verify_api_key(authorization)
    agents = _load_agents()
    workspaces = [_agent_to_workspace(a) for a in agents]
    return {"workspaces": workspaces}


@router.post("/v1/workspace/new")
async def create_workspace(request: WorkspaceCreateRequest, authorization: Optional[str] = Header(None)):
    """POST /v1/workspace/new — 创建 workspace。"""
    await verify_api_key(authorization)

    agents = _load_agents()

    # 检查名称重复
    if any(a["name"] == request.name for a in agents):
        raise HTTPException(status_code=400, detail=f"Workspace 名称 '{request.name}' 已存在")

    # name → slug 化（小写 + 连字符），作为 agent_id
    import re
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', request.name.lower()).strip('-')
    if not slug:
        slug = f"workspace-{uuid.uuid4().hex[:8]}"

    # 检查 slug 是否已存在
    if any(a.get("id") == slug for a in agents):
        raise HTTPException(status_code=400, detail=f"Workspace slug '{slug}' 已存在")

    now = datetime.now().isoformat()
    new_agent = {
        "id": slug,
        "name": request.name,
        "description": "",
        "system_prompt": "你是一个有帮助的AI助手。",
        "model": "main",
        "temperature": 0.7,
        "max_tokens": 4096,
        "use_memory": True,
        "use_tools": True,
        "memory_scene": "chat",
        "decay_model": "exponential",
        "vision_enabled": False,
        "is_default": False,
        "created_at": now,
        "updated_at": now,
    }

    agents.append(new_agent)
    _save_agents(agents)

    workspace = _agent_to_workspace(new_agent)
    return {"workspace": workspace, "message": "Workspace 创建成功"}


@router.get("/v1/workspace/{slug}")
async def get_workspace(slug: str, authorization: Optional[str] = Header(None)):
    """GET /v1/workspace/{slug} — 获取 workspace 详情。"""
    await verify_api_key(authorization)

    agent = _find_agent_by_slug(slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' 不存在")

    workspace = _agent_to_workspace_detail(agent)
    return {"workspace": workspace}


@router.post("/v1/workspace/{slug}/update")
async def update_workspace(slug: str, request: WorkspaceUpdateRequest, authorization: Optional[str] = Header(None)):
    """POST /v1/workspace/{slug}/update — 更新 workspace 设置。"""
    await verify_api_key(authorization)

    agents = _load_agents()
    agent_index = next((i for i, a in enumerate(agents) if a.get("id") == slug), None)

    if agent_index is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' 不存在")

    agent = agents[agent_index]

    # 更新字段
    if request.name is not None:
        agent["name"] = request.name
    if request.settings is not None:
        if "model" in request.settings:
            agent["model"] = request.settings["model"]
        if "temperature" in request.settings:
            agent["temperature"] = request.settings["temperature"]
        if "system_prompt" in request.settings:
            agent["system_prompt"] = request.settings["system_prompt"]

    agent["updated_at"] = datetime.now().isoformat()
    agents[agent_index] = agent
    _save_agents(agents)

    workspace = _agent_to_workspace_detail(agent)
    return {"workspace": workspace, "message": "Workspace 更新成功"}


@router.delete("/v1/workspace/{slug}")
async def delete_workspace(slug: str, authorization: Optional[str] = Header(None)):
    """DELETE /v1/workspace/{slug} — 删除 workspace。"""
    await verify_api_key(authorization)

    agents = _load_agents()
    agent = next((a for a in agents if a.get("id") == slug), None)

    if not agent:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' 不存在")

    if agent.get("is_default", False):
        raise HTTPException(status_code=400, detail="不能删除默认 Workspace")

    agents = [a for a in agents if a.get("id") != slug]
    _save_agents(agents)

    return {"success": True, "error": None}


# --- Phase 1: Workspace 聊天 ---

@router.post("/v1/workspace/{slug}/chat")
async def workspace_chat(slug: str, request: WorkspaceChatRequest, authorization: Optional[str] = Header(None)):
    """POST /v1/workspace/{slug}/chat — 非流式 workspace 聊天。

    支持：
    - mode: chat（完整历史+LLM）/ query（无历史+LLM）/ automatic（完整历史+LLM+工具）
    - reset: true 时清空会话历史
    - attachments: 文档附件解析为文本注入，图片附件传递给 LLM
    - 历史持久化：用户消息和 LLM 响应保存到 context_manager
    """
    await verify_api_key(authorization)

    agent = _find_agent_by_slug(slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' 不存在")

    llm = get_llm_client_for_agent(agent)
    if not llm:
        raise HTTPException(status_code=500, detail="LLM 客户端不可用")

    # 准备聊天上下文（公共逻辑：会话管理、reset、mode、attachments、消息构建）
    context_mgr, session_id, messages, kwargs = _prepare_chat_context(slug, request, agent)

    try:
        response = await llm.chat(messages, stream=False, **kwargs)
        text_response = response.content or ""

        # 持久化
        _persist_chat(context_mgr, session_id, request.message, text_response)

        return {
            "id": str(uuid.uuid4()),
            "textResponse": text_response,
            "sources": [],
            "mode": request.mode,
        }
    except Exception as e:
        logger.error(f"Workspace 聊天失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {str(e)}")


@router.post("/v1/workspace/{slug}/stream-chat")
async def workspace_stream_chat(slug: str, request: WorkspaceChatRequest, authorization: Optional[str] = Header(None)):
    """POST /v1/workspace/{slug}/stream-chat — 流式 workspace 聊天。

    返回标准 AnythingLLM SSE 格式：
        data: {"id":"<uuid>","type":"textResponseChunk","textResponse":"<chunk>","sources":[],"close":false,"error":null}\\n\\n
        ...
        data: {"id":"<uuid>","type":"textResponseChunk","textResponse":"","sources":[],"close":true,"error":null}\\n\\n

    错误时输出 type="abort" 的结束 chunk。
    """
    await verify_api_key(authorization)

    agent = _find_agent_by_slug(slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' 不存在")

    llm = get_llm_client_for_agent(agent)
    if not llm:
        raise HTTPException(status_code=500, detail="LLM 客户端不可用")

    # 准备聊天上下文（公共逻辑：会话管理、reset、mode、attachments、消息构建）
    context_mgr, session_id, messages, kwargs = _prepare_chat_context(slug, request, agent)

    chat_id = str(uuid.uuid4())

    def _sse_chunk(text: str, close: bool, error: Optional[str] = None) -> str:
        """构造 AnythingLLM 标准 SSE chunk。"""
        chunk_type = "abort" if error else "textResponseChunk"
        payload = {
            "id": chat_id,
            "type": chunk_type,
            "textResponse": text,
            "sources": [],
            "close": close,
            "error": error,
        }
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    # 用于在流式结束后保存完整响应
    collected_text = []

    async def stream_generator():
        try:
            async for chunk in llm.stream_chat(messages, **kwargs):
                if chunk.get("type") == "content":
                    text = chunk["content"]
                    collected_text.append(text)
                    yield _sse_chunk(text, close=False)
                elif chunk.get("type") == "error":
                    logger.error(f"LLM 流式错误: {chunk.get('content')}")
                    yield _sse_chunk("", close=True, error=str(chunk.get("content", "未知错误")))
                    return
            # 正常结束：输出 close=true 的结束 chunk
            yield _sse_chunk("", close=True)

            # 持久化（公共逻辑）
            full_response = "".join(collected_text)
            _persist_chat(context_mgr, session_id, request.message, full_response)
        except Exception as e:
            logger.error(f"流式聊天失败: {e}", exc_info=True)
            yield _sse_chunk("", close=True, error=str(e))

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/v1/workspace/{slug}/chats")
async def workspace_chats(slug: str, authorization: Optional[str] = Header(None)):
    """GET /v1/workspace/{slug}/chats — 获取聊天历史。"""
    await verify_api_key(authorization)

    agent = _find_agent_by_slug(slug)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Workspace '{slug}' 不存在")

    # 从 context_manager 获取聊天历史
    history = []
    try:
        from server.dependencies import get_context_manager
        context_mgr = get_context_manager()
        session_id = f"agent-{slug}"
        messages = context_mgr.get_recent_messages(session_id, limit=50)
        for msg in messages:
            if msg.get("role") in ["user", "assistant"]:
                history.append({
                    "id": msg.get("id", str(uuid.uuid4())),
                    "role": msg.get("role"),
                    "content": msg.get("content", ""),
                    "createdAt": msg.get("timestamp", datetime.now().isoformat()),
                })
    except Exception as e:
        logger.warning(f"获取聊天历史失败: {e}")

    return {"history": history}


# ========== Phase 2: Document 端点（7个） ==========

@router.post("/v1/document/upload")
async def upload_document(
    file: UploadFile = File(...),
    addToWorkspaces: Optional[str] = Form(None),
    metadata: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    dmm=Depends(get_document_memory_manager),
):
    """POST /v1/document/upload — 上传文件。

    multipart/form-data:
        file: 文件二进制
        addToWorkspaces: 可选，workspace slug
        metadata: 可选，JSON 字符串（title/author/description/source 等）

    Returns:
        {"success": bool, "documents": [{doc_name, title, word_count, ...}]}

    Raises:
        HTTPException(413): 文件超过大小限制
        HTTPException(500): 解析或持久化失败
    """
    await verify_api_key(authorization)

    # 解析 metadata JSON 字符串
    meta_dict = None
    if metadata:
        try:
            meta_dict = json.loads(metadata)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"metadata 不是合法 JSON: {e}")

    # 解析 workspaces
    workspaces = [addToWorkspaces] if addToWorkspaces else None

    # 读取文件内容
    try:
        file_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取文件失败: {e}")

    # 推断 mime（优先 file.content_type，回退到文件名推断）
    mime = file.content_type or "application/octet-stream"

    try:
        result = dmm.upload_file(
            file_bytes=file_bytes,
            filename=file.filename or "untitled",
            mime=mime,
            metadata=meta_dict,
            workspaces=workspaces,
        )
        return {"success": True, "documents": [result]}
    except ValueError as e:
        # 区分大小超限与解析失败
        msg = str(e)
        if "超过限制" in msg or "大小" in msg:
            raise HTTPException(status_code=413, detail=msg)
        raise HTTPException(status_code=500, detail=msg)
    except Exception as e:
        logger.error(f"文档上传失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文档上传失败: {e}")


@router.post("/v1/document/raw-text")
async def upload_raw_text(
    request: RawTextRequest,
    authorization: Optional[str] = Header(None),
    dmm=Depends(get_document_memory_manager),
):
    """POST /v1/document/raw-text — 通过文本创建文档。

    Returns:
        {"success": bool, "documents": [{doc_name, title, word_count, ...}]}

    Raises:
        HTTPException(500): 持久化失败
    """
    await verify_api_key(authorization)

    workspaces = [request.addToWorkspaces] if request.addToWorkspaces else None

    try:
        result = dmm.upload_text(
            text_content=request.textContent,
            metadata=request.metadata,
            workspaces=workspaces,
        )
        return {"success": True, "documents": [result]}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"文本上传失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文本上传失败: {e}")


@router.get("/v1/documents")
async def list_documents(
    authorization: Optional[str] = Header(None),
    dmm=Depends(get_document_memory_manager),
):
    """GET /v1/documents — 列出所有文档。

    Returns:
        {"localFiles": {"name": "documents", "type": "folder", "items": [...]}}
        items 中每个元素为文档摘要（不含 text_content）。
    """
    await verify_api_key(authorization)

    docs = dmm.list_documents()
    items = [_doc_row_to_response(d, include_text=False) for d in docs]
    return {
        "localFiles": {
            "name": "documents",
            "type": "folder",
            "items": items,
        }
    }


@router.get("/v1/document/metadata-schema")
async def get_metadata_schema(
    authorization: Optional[str] = Header(None),
):
    """GET /v1/document/metadata-schema — 获取元数据 schema。

    注意：此路由必须在 /v1/document/{docName} 之前定义，否则
    "metadata-schema" 会被当作 docName 参数匹配。

    Returns:
        {"schema": {field_name: field_type, ...}}
    """
    await verify_api_key(authorization)

    return {
        "schema": {
            "title": "string",
            "author": "string",
            "description": "string",
            "source": "string",
            "folder": "string",
            "file_path": "string",
            "mime_type": "string",
        }
    }


@router.get("/v1/document/{docName}")
async def get_document(
    docName: str,
    authorization: Optional[str] = Header(None),
    dmm=Depends(get_document_memory_manager),
):
    """GET /v1/document/{docName} — 获取单个文档详情。

    Args:
        docName: 文档唯一名（{title}-{uuid}.json）

    Returns:
        文档详情（含 text_content）

    Raises:
        HTTPException(404): 文档不存在
    """
    await verify_api_key(authorization)

    doc = dmm.get_document(docName)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 '{docName}' 不存在")
    return _doc_row_to_response(doc, include_text=True)


@router.delete("/v1/document/{docName}")
async def delete_document(
    docName: str,
    authorization: Optional[str] = Header(None),
    dmm=Depends(get_document_memory_manager),
):
    """DELETE /v1/document/{docName} — 删除文档（软删除 + 删除永久记忆）。

    Returns:
        {"success": bool}

    Raises:
        HTTPException(404): 文档不存在
    """
    await verify_api_key(authorization)

    success = dmm.delete_document(docName)
    if not success:
        raise HTTPException(status_code=404, detail=f"文档 '{docName}' 不存在")
    return {"success": True}


@router.post("/v1/workspace/{slug}/update-embeddings")
async def update_workspace_embeddings(
    slug: str,
    request: UpdateEmbeddingsRequest,
    authorization: Optional[str] = Header(None),
    dmm=Depends(get_document_memory_manager),
):
    """POST /v1/workspace/{slug}/update-embeddings — 管理 workspace 文档关联。

    Args:
        slug: workspace slug（= agent_id）
        request: {adds: List[str], deletes: List[str]}

    Returns:
        {"success": true, "added": [...], "removed": [...], "workspace": slug, "documents": [...]}

    Note:
        workspace 不存在时不抛 404（与 AnythingLLM 行为一致：workspace 按需创建关联）。
    """
    await verify_api_key(authorization)

    result = dmm.update_workspace_documents(
        slug=slug,
        adds=request.adds,
        deletes=request.deletes,
    )
    return {
        "success": True,
        "workspace": slug,
        "added": request.adds,
        "removed": request.deletes,
        "documents": result.get("documents", []),
    }
