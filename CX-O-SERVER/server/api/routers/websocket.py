"""
WebSocket 路由 - 提供实时双向通信
"""

from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.core.logging_config import get_contextual_logger
from server.core.websocket import get_websocket_manager
from server.services.live_client import LiveClientHandler

logger = get_contextual_logger(__name__)
router = APIRouter()


@router.websocket("/ws/{agent_id}")
async def websocket_agent_endpoint(websocket: WebSocket, agent_id: str, timeout: int = 60):
    """
    Agent 专用 WebSocket 端点

    前端主要使用的端点，支持自动关联 Agent 和离线超时配置

    Path 参数:
    - agent_id: Agent ID

    Query 参数:
    - timeout: 离线超时时间（秒），默认 60
    """
    ws_manager = get_websocket_manager()

    connection = await ws_manager.connect(
        websocket=websocket, metadata={"agent_id": agent_id, "timeout": timeout}
    )

    ws_manager.set_agent_timeout(agent_id, timeout)

    client_id = connection.client_id

    try:
        while True:
            message = await connection.receive()

            if "agent_id" not in message:
                message["agent_id"] = agent_id

            await ws_manager.handle_message(client_id, message)

    except WebSocketDisconnect:
        logger.info(f"WebSocket Agent 客户端断开连接: {client_id}, agent={agent_id}")
    except Exception as e:
        logger.error(f"WebSocket Agent 错误 {client_id}: {e}")
    finally:
        # L1: 清理统一挂 finally——asyncio.CancelledError 继承 BaseException，
        # 不被 except Exception 捕获，取消路径（uvicorn shutdown/任务取消）
        # 也必须释放连接与会话资源；disconnect 对不存在的 client_id 幂等
        # （与 gateway/server.py live handler 的 finally 先例一致）。
        # R9-01: 携带本连接代际，disconnect 代际校验防同 id 重连后
        # 旧端点 finally 拆毁新会话。
        await ws_manager.disconnect(client_id, generation=connection.generation)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, client_id: Optional[str] = None, token: Optional[str] = None
):
    """
    WebSocket 连接端点

    支持实时聊天、消息订阅、心跳检测等功能

    Query 参数:
    - client_id: 客户端ID（可选，不传则自动生成）
    - token: 认证令牌（可选）
    """
    ws_manager = get_websocket_manager()

    # 建立连接
    connection = await ws_manager.connect(
        websocket=websocket, client_id=client_id, metadata={"token": token} if token else {}
    )

    client_id = connection.client_id

    try:
        # 保持连接并处理消息
        while True:
            # 接收消息
            message = await connection.receive()

            # 处理消息
            await ws_manager.handle_message(client_id, message)

    except WebSocketDisconnect:
        logger.info(f"WebSocket 客户端断开连接: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket 错误 {client_id}: {e}")
    finally:
        # L1: 清理统一挂 finally，覆盖 CancelledError 取消路径；disconnect 幂等。
        # R9-01: 携带本连接代际，防同 id 重连后旧端点 finally 拆毁新会话。
        await ws_manager.disconnect(client_id, generation=connection.generation)


@router.websocket("/ws/chat")
async def websocket_chat_endpoint(
    websocket: WebSocket, session_id: Optional[str] = None, agent_id: Optional[str] = "default"
):
    """
    WebSocket 聊天专用端点

    简化版聊天连接，自动订阅到指定会话

    Query 参数:
    - session_id: 会话ID（可选）
    - agent_id: Agent ID（可选，默认 default）
    """
    ws_manager = get_websocket_manager()

    # 建立连接
    connection = await ws_manager.connect(
        websocket=websocket, metadata={"session_id": session_id, "agent_id": agent_id}
    )

    client_id = connection.client_id

    # 如果有会话ID，订阅到该会话频道
    if session_id:
        ws_manager.subscribe_to_channel(client_id, f"session:{session_id}")

    try:
        while True:
            message = await connection.receive()

            # 自动添加会话和Agent信息
            if "session_id" not in message and session_id:
                message["session_id"] = session_id
            if "agent_id" not in message and agent_id:
                message["agent_id"] = agent_id

            await ws_manager.handle_message(client_id, message)

    except WebSocketDisconnect:
        logger.info(f"WebSocket 聊天客户端断开连接: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket 聊天错误 {client_id}: {e}")
    finally:
        # L1: 清理统一挂 finally，覆盖 CancelledError 取消路径；disconnect 幂等。
        # R9-01: 携带本连接代际，防同 id 重连后旧端点 finally 拆毁新会话。
        await ws_manager.disconnect(client_id, generation=connection.generation)


@router.websocket("/ws/live")
async def websocket_live_endpoint(
    websocket: WebSocket, session_id: Optional[str] = None
):
    """
    直播专用 WebSocket 端点

    用于直播场景的实时通信，支持弹幕、音频、TTS 同步等

    Query 参数:
    - session_id: 会话ID（可选）
    """
    ws_manager = get_websocket_manager()

    connection = await ws_manager.connect(
        websocket=websocket, metadata={"session_id": session_id, "type": "live"}
    )

    client_id = connection.client_id

    ws_manager.subscribe_to_channel(client_id, "live")

    live_handler = LiveClientHandler(ws_manager, client_id, {})

    try:
        while True:
            raw = await websocket.receive()

            if "bytes" in raw:
                await live_handler.handle_audio(websocket, raw["bytes"], client_id)
            elif "text" in raw:
                import json
                try:
                    message = json.loads(raw["text"])
                except json.JSONDecodeError:
                    logger.warning(f"Live client sent invalid JSON: {raw['text'][:100]}")
                    continue

                await live_handler.handle_message(websocket, message, client_id)

    except WebSocketDisconnect:
        logger.info(f"直播客户端断开连接: {client_id}")
        # per-client 实例随 client 生命周期在 manager.disconnect 中释放，无需补丁重置
    except Exception as e:
        logger.error(f"直播 WebSocket 错误 {client_id}: {e}")
        # per-client 实例随 client 生命周期在 manager.disconnect 中释放，无需补丁重置
    finally:
        # L1: 清理统一挂 finally——CancelledError 取消路径同样释放 per-client
        # 双流会话/VAD/ASR流式会话/打断模块；disconnect 幂等。
        # R9-01: 携带本连接代际，防同 id 重连后旧端点 finally 拆毁新会话。
        await ws_manager.disconnect(client_id, generation=connection.generation)
