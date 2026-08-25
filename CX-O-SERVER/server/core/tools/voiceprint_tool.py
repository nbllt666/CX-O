"""
声纹识别工具（LLM 工具调用注册声纹）。

register_voiceprint 基于当前语音会话的最近临时说话人 embedding 建档，
不重新提取音频特征；注册在后台异步执行，不阻塞 LLM 回复。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Any

from server.core.tools.registry import tool_registry

logger = logging.getLogger(__name__)

# 后台注册任务集合（防 GC：asyncio 不持有裸 create_task 引用）
_voice_tasks: set = set()


async def _register_and_notify(client_id: str, name: str, embedding: list) -> None:
    """后台执行注册并推送 voice.voiceprint_result 事件。"""
    from server.services import voiceprint_service
    from server.core.websocket.manager import get_websocket_manager

    try:
        summary = await voiceprint_service.register_embedding(name, embedding)
        data = {
            "ok": True,
            "name": name,
            "embeddings_count": summary.get("embeddings_count", 0),
        }
    except ValueError as e:
        data = {"ok": False, "name": name, "detail": str(e)}
    except Exception as e:  # noqa: BLE001 落盘 IO / 其它兜底
        logger.error(f"声纹注册异常: {e}")
        data = {"ok": False, "name": name, "detail": str(e)}
    try:
        await get_websocket_manager().send_message(client_id, {
            "type": "voice.voiceprint_result",
            "data": data,
        })
    except Exception as e:  # noqa: BLE001 通道不可用仅告警
        logger.warning(f"voice.voiceprint_result 推送失败（client_id={client_id}）: {e}")


def _spawn_voice_task(client_id: str, name: str, embedding: list) -> None:
    """创建后台注册任务并持引用防 GC；任务完成时自动从集合移除。"""
    task = asyncio.create_task(_register_and_notify(client_id, name, embedding))
    _voice_tasks.add(task)
    task.add_done_callback(_voice_tasks.discard)


async def _handler(name: str) -> Dict[str, Any]:
    """register_voiceprint 工具 handler：基于最近临时说话人 embedding 注册。

    参数 name：要注册的说话人名。无可用 embedding（文本聊天/会话刚开始）时
    返回明确中文错误，不发起注册。
    """
    from server.services import asr_service
    from server.services.voice_context import get_active_client_id

    client_id = get_active_client_id()
    embedding = asr_service.get_recent_spk_embedding(client_id)
    if not embedding:
        return {
            "success": False,
            "error": "未检测到你的声纹，请先对着麦克风清晰地说一句话，再让我记住你的声音。",
            "tool_name": "register_voiceprint",
        }

    _spawn_voice_task(client_id, name, embedding)
    return {
        "success": True,
        "status": "registering",
        "name": name,
        "message": "正在保存你的声音档案，稍后告诉你结果。",
    }


def register_voiceprint_tool() -> None:
    """注册 register_voiceprint 工具（幂等）。"""
    tool_registry.register(
        name="register_voiceprint",
        description=(
            "为用户注册声纹档案。用户在语音对话中说出类似"
            "\"记住我的声音，我叫XX\"的请求时调用，参数 name 为说话人名。"
        ),
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "要注册的说话人名"}},
            "required": ["name"],
        },
        function=_handler,
        enabled=True,
        version="1.0.0",
        category="general",
        tags=["voiceprint"],
        examples=["记住我的声音，我叫小明 → register_voiceprint(name='小明')"],
    )