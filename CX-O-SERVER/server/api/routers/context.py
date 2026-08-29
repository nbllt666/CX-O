"""上下文端点——对话上下文查询与历史格式化接口。"""
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# 修复：批量替换事故导致 run_io 重复导入 84 次，收敛为单次导入（实际使用：run_io + format_messages_for_summary）
from server.core.utils import format_messages_for_summary, run_io

router = APIRouter()


class SessionCreateRequest(BaseModel):
    workspace_id: str = "default"
    title: str = ""
    metadata: Dict = {}


class MessageCreateRequest(BaseModel):
    session_id: str
    role: str
    content: str
    content_type: str = "text"
    metadata: Dict = {}


@router.get("/context/sessions")
async def list_sessions(workspace_id: str = "default", limit: int = 20, active_only: bool = True):
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 异步变体：get_sessions 的 sqlite 查询移入 IO 线程池，避免阻塞事件循环
        sessions = await context_mgr.get_sessions_async(
            workspace_id=workspace_id, limit=limit, active_only=active_only
        )
        return {"status": "success", "sessions": sessions, "total": len(sessions)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/sessions")
async def create_session(request: SessionCreateRequest):
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 异步变体：create_session 的 sqlite 写入移入 IO 线程池
        session_id = await context_mgr.create_session_async(
            workspace_id=request.workspace_id, title=request.title, metadata=request.metadata
        )
        return {"status": "success", "session_id": session_id, "message": "会话创建成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/sessions/{session_id}")
async def get_session(session_id: str):
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 异步变体：get_session 的 sqlite 查询移入 IO 线程池
        session = await context_mgr.get_session_async(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        return {"status": "success", "session": session}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/context/sessions/{session_id}/messages")
async def clear_session_messages(session_id: str):
    """清空会话消息（保留会话）

    迁移自 CXHMS: backend/api/routers/context.py:L72-L86
    """
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 无 async 变体：经 run_io 把同步 sqlite 移入 IO 线程池
        success = await run_io(context_mgr.clear_session_messages, session_id)
        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"status": "success", "message": "会话消息已清空"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/context/sessions/all")
async def clear_all_sessions():
    """删除所有会话和消息。

    注意：本路由必须在 /context/sessions/{session_id} 之前注册，
    否则 /all 会被 {session_id} 路径参数吞掉导致本端点不可达。
    """
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 无 async 变体：经 run_io 把同步 sqlite 移入 IO 线程池
        count = await run_io(context_mgr.clear_all_sessions)

        return {"status": "success", "message": f"已删除 {count} 个会话", "deleted_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/context/sessions/{session_id}")
async def delete_session(session_id: str):
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 无 async 变体：经 run_io 把同步 sqlite 移入 IO 线程池
        success = await run_io(context_mgr.delete_session, session_id)

        if not success:
            raise HTTPException(status_code=404, detail="会话不存在")

        return {"status": "success", "message": "会话删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/messages/{session_id}")
async def get_messages(session_id: str, limit: int = 50, offset: int = 0):
    """获取指定会话的消息列表。"""
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 异步变体：get_messages 的 sqlite 查询移入 IO 线程池
        messages = await context_mgr.get_messages_async(session_id=session_id, limit=limit, offset=offset)
        return {
            "status": "success",
            "session_id": session_id,
            "messages": messages,
            "total": len(messages),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/messages")
async def add_message(request: MessageCreateRequest):
    from server.dependencies import get_context_manager

    valid_roles = {"system", "user", "assistant", "tool"}
    if request.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 role: {request.role}, 必须是 {sorted(valid_roles)} 之一",
        )

    try:
        context_mgr = get_context_manager()
        # 异步变体：add_message 的 sqlite 写入移入 IO 线程池
        message_id = await context_mgr.add_message_async(
            session_id=request.session_id,
            role=request.role,
            content=request.content,
            content_type=request.content_type,
            metadata=request.metadata,
        )
        return {"status": "success", "message_id": message_id, "message": "消息添加成功"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/context/summary")
async def generate_summary(session_id: str, max_points: int = 5, save_as_memory: bool = True):
    """使用摘要模型生成对话摘要和报告"""
    from server.dependencies import get_context_manager, get_memory_manager, get_model_router

    try:
        context_mgr = get_context_manager()
        model_router = get_model_router()
        memory_manager = get_memory_manager()

        # 获取对话消息（取最近 100 条，避免 get_messages 返回最旧消息导致摘要陈旧）
        # 异步变体：get_recent_messages 的 sqlite 查询移入 IO 线程池
        messages = await context_mgr.get_recent_messages_async(session_id, limit=100)
        if not messages:
            raise HTTPException(status_code=404, detail="会话不存在或为空")

        # 获取摘要模型客户端
        summary_client = None
        if model_router:
            summary_client = model_router.get_client("summary")

        if not summary_client:
            raise HTTPException(status_code=503, detail="摘要模型不可用")

        # 格式化对话内容
        conversation_text = format_messages_for_summary(messages)
        message_count = len(messages)

        # 调用摘要模型生成深度分析
        import json
        from datetime import datetime

        prompt = f"""你是一位专业的对话分析专家。请对以下对话进行深度分析，生成结构化摘要报告。

## 对话内容
{conversation_text}

## 分析要求

### 1. 关键要点 (key_points)
提取{max_points}个核心要点，每个要点包含：
- content: 要点内容（简洁描述，不超过50字）
- importance: 重要性（high/medium/low）
- participants: 涉及角色（["user"]/["assistant"]/["user", "assistant"]）

### 2. 完整报告 (report)
- topic: 对话主题（一句话概括，不超过30字）
- participants: 参与者列表（如["user", "assistant"]）
- message_count: 消息总数（{message_count}）
- main_discussion: 主要讨论内容摘要（200-300字，分段描述关键讨论点）
- key_decisions: 关键决策/结论列表（字符串数组）
- action_items: 行动项列表（如有，每项包含任务描述）
- open_questions: 未解决问题列表（如有）
- sentiment: 整体情感倾向（positive/neutral/negative）
- sentiment_analysis: 情感分析说明（50字内，解释情感倾向的原因）
- timeline: 对话时间线（关键节点数组，每个节点包含time和event）

请以严格的JSON格式返回，确保可以被解析：
{{
    "key_points": [
        {{"content": "...", "importance": "high", "participants": ["user"]}},
        ...
    ],
    "report": {{
        "topic": "...",
        "participants": ["user", "assistant"],
        "message_count": {message_count},
        "main_discussion": "...",
        "key_decisions": ["..."],
        "action_items": ["..."],
        "open_questions": ["..."],
        "sentiment": "positive",
        "sentiment_analysis": "...",
        "timeline": [{{"time": "开始", "event": "..."}}]
    }}
}}"""

        response = await summary_client.chat(
            messages=[{"role": "user", "content": prompt}], stream=False, max_tokens=2048
        )

        # 解析模型响应
        try:
            if hasattr(response, "content"):
                result_text = response.content
            elif isinstance(response, dict):
                result_text = response.get("content", "")
            else:
                result_text = str(response)

            # 尝试提取JSON部分
            json_start = result_text.find("{")
            json_end = result_text.rfind("}")
            if json_start != -1 and json_end != -1:
                result_text = result_text[json_start : json_end + 1]

            result = json.loads(result_text)
            key_points = result.get("key_points", [])
            report = result.get("report", {})
        except Exception:
            # 解析失败时使用简化结果
            key_points = []
            report = {
                "topic": "对话摘要",
                "participants": ["user", "assistant"],
                "message_count": message_count,
                "main_discussion": (
                    conversation_text[:300] if len(conversation_text) > 300 else conversation_text
                ),
                "sentiment": "neutral",
            }

        # 生成摘要文本
        summary_text = report.get("topic", "") + "\n\n"
        summary_text += "关键要点：\n"
        for i, point in enumerate(key_points[:max_points], 1):
            summary_text += f"{i}. {point.get('content', '')}\n"

        # 保存为记忆
        summary_memory_id = None
        if save_as_memory and memory_manager:
            try:
                summary_memory_id = await memory_manager.write_memory(
                    content=summary_text,
                    memory_type="conversation_summary",
                    importance=4,
                    tags=["conversation_summary", session_id],
                    metadata={
                        "conversation_id": session_id,
                        "key_points": key_points,
                        "report": report,
                        "message_count": message_count,
                        "summarized_at": datetime.now().isoformat(),
                    },
                )
            except Exception as e:
                import logging

                logging.getLogger(__name__).error(f"保存摘要记忆失败: {e}")

        # 更新会话摘要
        # 异步变体：update_session 的 sqlite 写入移入 IO 线程池
        await context_mgr.update_session_async(session_id, summary=summary_text[:500])

        return {
            "status": "success",
            "conversation_id": session_id,
            "summary_memory_id": summary_memory_id,
            "key_points": key_points,
            "report": report,
            "metadata": {
                "original_message_count": message_count,
                "summary_generated_at": datetime.now().isoformat(),
                "model_used": "summary",
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context/stats")
async def get_context_stats(workspace_id: str = "default"):
    """获取上下文统计信息。"""
    from server.dependencies import get_context_manager

    try:
        context_mgr = get_context_manager()
        # 异步变体：get_statistics 的 sqlite 聚合查询移入 IO 线程池
        stats = await context_mgr.get_statistics_async(workspace_id)

        return {"status": "success", "statistics": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
