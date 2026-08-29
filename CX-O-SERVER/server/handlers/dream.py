"""
梦境 WebSocket 处理器（C→S 入向：dream.confirm / dream.reject）

C→S 消息走 {action, request_id, data} 约定，经 ws_manager 的 action 路由
（gateway/server.py websocket_handler → get_handler）分发到本模块注册的处理器；
处理器懒取 DreamConsolidator（经 server.autonomy.main 模块级 _dream_engine
单例，dream.enabled 时由 setup_autonomy 装配）执行固化/否定，并回发
{action, request_id, ok, data}（对齐 spec "WebSocket 协议"）。
"""
import asyncio
import logging
from typing import TYPE_CHECKING, Dict, Any

from server.protocol.message import create_response, create_error
from server.protocol.actions import DreamActions

if TYPE_CHECKING:
    from server.core.websocket.manager import WebSocketManager

logger = logging.getLogger(__name__)


def _get_consolidator():
    """懒取梦境固化器（DreamConsolidator）。

    经 server.autonomy.main 模块级 _dream_engine 单例（dream.enabled 时由
    setup_autonomy 装配）；未启用 / 未装配 / 装配失败返回 None。函数内延迟
    import 避免模块加载期循环依赖。
    """
    try:
        from server.autonomy.main import _dream_engine
    except Exception:
        return None
    if _dream_engine is None:
        return None
    return getattr(_dream_engine, "_consolidator", None)


def _payload(message: Dict[str, Any]) -> Dict[str, Any]:
    """读取 C→S 消息的 data 载荷（缺失返回空 dict）。"""
    data = message.get("data")
    return data if isinstance(data, dict) else {}


def register_dream_handlers(manager: "WebSocketManager"):
    """将梦境 C→S 处理器注册到 WebSocket 管理器（action 路由）。"""

    async def handle_dream_confirm(websocket, message, client_id):
        request_id = message.get("request_id", "")
        consolidator = _get_consolidator()
        if consolidator is None:
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=DreamActions.CONFIRM,
                code="DREAM_DISABLED",
                message="梦境引擎未启用",
            ))
            return
        try:
            data = _payload(message)
            # consolidate 涉及主库写，同步直调会阻塞事件循环 → 移入线程执行
            memory_id = await asyncio.to_thread(
                consolidator.consolidate,
                data.get("buffer_id"), data.get("agent_id", "default")
            )
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=DreamActions.CONFIRM,
                data={"ok": memory_id is not None, "memory_id": memory_id},
            ))
        except Exception as e:
            logger.error(f"Dream confirm error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=DreamActions.CONFIRM,
                code="DREAM_CONFIRM_ERROR",
                message=str(e),
            ))

    async def handle_dream_reject(websocket, message, client_id):
        request_id = message.get("request_id", "")
        consolidator = _get_consolidator()
        if consolidator is None:
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=DreamActions.REJECT,
                code="DREAM_DISABLED",
                message="梦境引擎未启用",
            ))
            return
        try:
            data = _payload(message)
            # reject 同样涉及主库写，移入线程避免阻塞事件循环
            ok = await asyncio.to_thread(
                consolidator.reject,
                data.get("buffer_id"),
                data.get("agent_id", "default"),
                data.get("reason", ""),
            )
            await manager.send_message(client_id, create_response(
                request_id=request_id,
                action=DreamActions.REJECT,
                data={"ok": ok},
            ))
        except Exception as e:
            logger.error(f"Dream reject error: {e}")
            await manager.send_message(client_id, create_error(
                request_id=request_id,
                action=DreamActions.REJECT,
                code="DREAM_REJECT_ERROR",
                message=str(e),
            ))

    manager.register_action_handler(DreamActions.CONFIRM, handle_dream_confirm)
    manager.register_action_handler(DreamActions.REJECT, handle_dream_reject)
