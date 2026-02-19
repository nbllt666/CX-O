"""
记忆管理对话 API 路由
提供与记忆管理模型的自然语言交互接口
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)


class MemoryChatRequest(BaseModel):
    """记忆管理对话请求"""

    message: str
    session_id: str = "default"


class MemoryChatResponse(BaseModel):
    """记忆管理对话响应"""

    status: str
    message: str
    session_id: str
    pending_command: Optional[Dict] = None
    data: Optional[Dict] = None


@router.post("/memory-chat", response_model=MemoryChatResponse)
async def memory_chat(request: MemoryChatRequest):
    """
    与记忆管理模型对话

    支持自然语言指令管理记忆：
    - 搜索记忆
    - 归档记忆
    - 合并重复记忆
    - 删除记忆
    - 检测重复
    - 查看统计
    """
    from backend.api.app import get_memory_manager, get_model_router

    try:
        memory_mgr = get_memory_manager()

        if not memory_mgr:
            raise HTTPException(status_code=503, detail="记忆服务不可用")

        if not hasattr(memory_mgr, "conversation_engine") or memory_mgr.conversation_engine is None:
            from backend.core.memory.conversation import MemoryConversationEngine

            llm_client = None
            try:
                model_router = get_model_router()
                if model_router:
                    llm_client = model_router.get_client("memory")
            except Exception as e:
                logger.warning(f"获取模型路由器失败: {e}")

            memory_mgr.conversation_engine = MemoryConversationEngine(
                memory_manager=memory_mgr, llm_client=llm_client
            )
            logger.info("记忆管理对话引擎已初始化")

        result = await memory_mgr.conversation_engine.process_message(
            user_message=request.message, session_id=request.session_id
        )

        return MemoryChatResponse(
            status=result.get("status", "unknown"),
            message=result.get("message", ""),
            session_id=request.session_id,
            pending_command=result.get("pending_command"),
            data={
                k: v for k, v in result.items() if k not in ["status", "message", "pending_command"]
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"记忆管理对话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")


@router.get("/memory-chat/sessions/{session_id}")
async def get_chat_session(session_id: str):
    """获取对话会话历史"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if not memory_mgr or not hasattr(memory_mgr, "conversation_engine"):
            raise HTTPException(status_code=503, detail="对话服务不可用")

        context = memory_mgr.conversation_engine.get_or_create_session(session_id)

        return {
            "status": "success",
            "session_id": session_id,
            "messages": context.messages,
            "has_pending_command": context.pending_command is not None,
            "pending_command": (
                {
                    "type": context.pending_command.command_type,
                    "description": context.pending_command.description,
                }
                if context.pending_command
                else None
            ),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取会话失败: {str(e)}")


@router.delete("/memory-chat/sessions/{session_id}")
async def clear_chat_session(session_id: str):
    """清除对话会话"""
    from backend.api.app import get_memory_manager

    try:
        memory_mgr = get_memory_manager()

        if not memory_mgr or not hasattr(memory_mgr, "conversation_engine"):
            raise HTTPException(status_code=503, detail="对话服务不可用")

        if session_id in memory_mgr.conversation_engine._sessions:
            del memory_mgr.conversation_engine._sessions[session_id]

        return {"status": "success", "message": f"会话 {session_id} 已清除"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"清除会话失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"清除会话失败: {str(e)}")


@router.get("/memory-chat/commands")
async def list_available_commands():
    """列出可用的记忆管理命令"""
    from backend.core.memory.conversation import MemoryConversationEngine

    try:
        commands = {
            cmd: desc
            for cmd, desc in MemoryConversationEngine.COMMAND_TYPES.items()
            if cmd != "unknown"
        }

        destructive_commands = MemoryConversationEngine.DESTRUCTIVE_COMMANDS

        return {
            "status": "success",
            "commands": commands,
            "destructive_commands": destructive_commands,
            "examples": [
                {"command": "搜索关于人工智能的记忆", "description": "搜索包含特定关键词的记忆"},
                {"command": "归档记忆 ID 123", "description": "将指定记忆归档"},
                {"command": "合并重复记忆", "description": "自动检测并合并重复记忆"},
                {"command": "检测重复", "description": "检测系统中的重复记忆"},
                {"command": "查看统计", "description": "查看记忆系统统计信息"},
                {"command": "帮助", "description": "显示帮助信息"},
            ],
        }

    except Exception as e:
        logger.error(f"获取命令列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取命令列表失败: {str(e)}")
