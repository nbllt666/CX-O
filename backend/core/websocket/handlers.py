import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from backend.core.logging_config import get_contextual_logger

from .manager import get_websocket_manager

logger = get_contextual_logger(__name__)


class ChatWebSocketHandler:
    """聊天 WebSocket 处理器

    处理通过 WebSocket 的实时聊天消息
    """

    def __init__(self):
        self.ws_manager = get_websocket_manager()
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_flags: Dict[str, bool] = {}
        self._register_handlers()

    def _register_handlers(self):
        """注册消息处理器"""
        self.ws_manager.register_handler("chat", self._handle_chat)
        self.ws_manager.register_handler("chat_stream", self._handle_chat_stream)
        self.ws_manager.register_handler("subscribe", self._handle_subscribe)
        self.ws_manager.register_handler("unsubscribe", self._handle_unsubscribe)
        self.ws_manager.register_handler("ping", self._handle_ping)
        self.ws_manager.register_handler("cancel", self._handle_cancel)
        self.ws_manager.register_handler("config", self._handle_config)

    async def _handle_chat(self, client_id: str, message: Dict[str, Any]):
        """处理普通聊天消息"""
        from backend.api.app import get_context_manager, get_memory_manager
        from backend.api.routers.chat import (
            build_messages,
            get_agent_config,
            get_llm_client_for_agent,
        )

        try:
            agent_id = message.get("agent_id", "default")
            session_id = message.get("session_id")
            user_message = message.get("message", "")

            if not user_message:
                await self.ws_manager.send_to_client(
                    client_id, {"type": "error", "error": "消息不能为空"}
                )
                return

            # 获取配置
            agent_config = get_agent_config(agent_id)
            if not agent_config:
                await self.ws_manager.send_to_client(
                    client_id, {"type": "error", "error": f"Agent '{agent_id}' 不存在"}
                )
                return

            # 获取管理器
            memory_mgr = get_memory_manager()
            context_mgr = get_context_manager()
            llm = get_llm_client_for_agent(agent_config)

            # 获取/创建会话
            if session_id:
                try:
                    context_mgr.get_session(session_id)
                except Exception:
                    await self.ws_manager.send_to_client(
                        client_id, {"type": "error", "error": f"会话 '{session_id}' 不存在"}
                    )
                    return
            else:
                session_id = context_mgr.create_session(
                    workspace_id="default", title=f"与 {agent_config['name']} 的对话"
                )

            # 添加用户消息
            context_mgr.add_message(session_id=session_id, role="user", content=user_message)

            # 检索记忆
            memory_context = None
            if agent_config.get("use_memory", True) and memory_mgr:
                from backend.core.memory.router import MemoryRouter

                router = MemoryRouter(memory_manager=memory_mgr)
                routing_result = await router.route(
                    query=user_message,
                    session_id=session_id,
                    scene_type=agent_config.get("memory_scene", "chat"),
                )
                if routing_result.memories:
                    memory_context = "\n".join(
                        [f"- {m['content']}" for m in routing_result.memories[:5]]
                    )

            # 构建消息列表
            messages = build_messages(
                agent_config=agent_config,
                context_mgr=context_mgr,
                session_id=session_id,
                user_message=user_message,
                memory_context=memory_context,
            )

            # 调用 LLM
            response = await llm.chat(messages=messages, stream=False)

            # 保存助手响应
            context_mgr.add_message(
                session_id=session_id, role="assistant", content=response.content
            )

            # 发送响应
            await self.ws_manager.send_to_client(
                client_id,
                {
                    "type": "chat_response",
                    "session_id": session_id,
                    "content": response.content,
                    "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"处理聊天消息失败: {e}")
            await self.ws_manager.send_to_client(client_id, {"type": "error", "error": str(e)})

    async def _handle_chat_stream(self, client_id: str, message: Dict[str, Any]):
        """处理流式聊天消息"""
        from backend.api.app import get_context_manager, get_memory_manager
        from backend.api.routers.chat import (
            build_messages,
            get_agent_config,
            get_llm_client_for_agent,
        )

        try:
            agent_id = message.get("agent_id", "default")
            session_id = message.get("session_id")
            user_message = message.get("message", "")

            if not user_message:
                await self.ws_manager.send_to_client(
                    client_id, {"type": "error", "error": "消息不能为空"}
                )
                return

            # 获取配置
            agent_config = get_agent_config(agent_id)
            if not agent_config:
                await self.ws_manager.send_to_client(
                    client_id, {"type": "error", "error": f"Agent '{agent_id}' 不存在"}
                )
                return

            # 获取管理器
            memory_mgr = get_memory_manager()
            context_mgr = get_context_manager()
            llm = get_llm_client_for_agent(agent_config)

            # 获取/创建会话
            if session_id:
                try:
                    context_mgr.get_session(session_id)
                except Exception:
                    await self.ws_manager.send_to_client(
                        client_id, {"type": "error", "error": f"会话 '{session_id}' 不存在"}
                    )
                    return
            else:
                session_id = context_mgr.create_session(
                    workspace_id="default", title=f"与 {agent_config['name']} 的对话"
                )

            # 发送会话ID
            await self.ws_manager.send_to_client(
                client_id, {"type": "session_info", "session_id": session_id}
            )

            # 添加用户消息
            context_mgr.add_message(session_id=session_id, role="user", content=user_message)

            # 检索记忆
            memory_context = None
            if agent_config.get("use_memory", True) and memory_mgr:
                from backend.core.memory.router import MemoryRouter

                router = MemoryRouter(memory_manager=memory_mgr)
                routing_result = await router.route(
                    query=user_message,
                    session_id=session_id,
                    scene_type=agent_config.get("memory_scene", "chat"),
                )
                if routing_result.memories:
                    memory_context = "\n".join(
                        [f"- {m['content']}" for m in routing_result.memories[:5]]
                    )

            # 构建消息列表
            messages = build_messages(
                agent_config=agent_config,
                context_mgr=context_mgr,
                session_id=session_id,
                user_message=user_message,
                memory_context=memory_context,
            )

            # 流式响应
            full_response = ""
            self._cancel_flags[client_id] = False

            async for chunk in llm.stream_chat(
                messages=messages,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=agent_config.get("max_tokens", 4096),
            ):
                if self._cancel_flags.get(client_id, False):
                    await self.ws_manager.send_to_client(
                        client_id, {"type": "cancelled", "timestamp": datetime.now().isoformat()}
                    )
                    return

                if chunk:
                    full_response += chunk
                    await self.ws_manager.send_to_client(
                        client_id, {"type": "chat_chunk", "content": chunk}
                    )

            # 保存完整响应
            if full_response:
                context_mgr.add_message(
                    session_id=session_id, role="assistant", content=full_response
                )

            # 发送完成消息
            await self.ws_manager.send_to_client(
                client_id,
                {
                    "type": "chat_done",
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        except Exception as e:
            logger.error(f"处理流式聊天消息失败: {e}")
            await self.ws_manager.send_to_client(client_id, {"type": "error", "error": str(e)})

    async def _handle_subscribe(self, client_id: str, message: Dict[str, Any]):
        """处理订阅请求"""
        channel = message.get("channel", "")
        if channel:
            self.ws_manager.subscribe_to_channel(client_id, channel)
            await self.ws_manager.send_to_client(
                client_id, {"type": "subscribed", "channel": channel}
            )

    async def _handle_unsubscribe(self, client_id: str, message: Dict[str, Any]):
        """处理取消订阅请求"""
        channel = message.get("channel", "")
        if channel:
            self.ws_manager.unsubscribe_from_channel(client_id, channel)
            await self.ws_manager.send_to_client(
                client_id, {"type": "unsubscribed", "channel": channel}
            )

    async def _handle_ping(self, client_id: str, message: Dict[str, Any]):
        """处理心跳"""
        await self.ws_manager.send_to_client(
            client_id, {"type": "pong", "timestamp": datetime.now().isoformat()}
        )

    async def _handle_cancel(self, client_id: str, message: Dict[str, Any]):
        """处理取消响应请求"""
        logger.info(f"客户端 {client_id} 请求取消响应")
        self._cancel_flags[client_id] = True
        await self.ws_manager.send_to_client(
            client_id, {"type": "cancelled", "timestamp": datetime.now().isoformat()}
        )

    async def _handle_config(self, client_id: str, message: Dict[str, Any]):
        """处理配置更新"""
        if "timeout" in message:
            timeout = message["timeout"]
            if client_id in self.ws_manager.connections:
                self.ws_manager.connections[client_id].metadata["timeout"] = timeout
            await self.ws_manager.send_to_client(
                client_id, {"type": "config_updated", "timeout": timeout}
            )


async def push_alarm_to_agent(agent_id: str, alarm_message: str):
    """向指定 Agent 推送提醒消息"""
    from .manager import get_websocket_manager

    ws_manager = get_websocket_manager()

    await ws_manager.broadcast_to_channel(
        f"agent:{agent_id}",
        {"type": "alarm", "message": alarm_message, "triggered_at": datetime.now().isoformat()},
    )
    logger.info(f"已向 Agent {agent_id} 推送提醒: {alarm_message}")


# 全局处理器实例
_chat_handler: Optional[ChatWebSocketHandler] = None


def get_chat_handler() -> ChatWebSocketHandler:
    """获取全局聊天处理器实例"""
    global _chat_handler
    if _chat_handler is None:
        _chat_handler = ChatWebSocketHandler()
    return _chat_handler
