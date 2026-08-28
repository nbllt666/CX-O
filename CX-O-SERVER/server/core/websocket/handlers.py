"""WebSocket 聊天处理器——通过 WebSocket 处理实时聊天消息。"""
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional

from server.core.logging_config import get_contextual_logger
from server.core.utils import run_io

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

    @staticmethod
    def _ensure_agent_session(context_mgr, agent_id: str, agent_config: dict) -> str:
        """确保 agent-{agent_id} 会话存在并返回其 ID。

        与 GET /api/chat/history/agent-{id} 的历史读取键保持一致（workspace=agent-chats），
        使 WS 聊天写入与前端历史读取落在同一会话，修复「前端不加载历史记录」。
        """
        session_id = f"agent-{agent_id}"
        if not context_mgr.get_session(session_id):
            context_mgr.create_session(
                session_id=session_id,
                workspace_id="agent-chats",
                title=f"与 {agent_config.get('name', 'Agent')} 的对话",
            )
            context_mgr.update_session(session_id, metadata={"agent_id": agent_id})
        return session_id

    async def _handle_chat(self, client_id: str, message: Dict[str, Any]):
        """处理普通聊天消息"""
        from server.dependencies import get_context_manager, get_memory_manager
        from server.chat_helpers import get_agent_config, get_llm_client_for_agent, retrieve_memory_context
        from server.prompt_builder import build_messages

        try:
            agent_id = message.get("agent_id", "default")
            session_id = message.get("session_id")
            user_message = message.get("message", "")

            if not user_message:
                await self.ws_manager.send_to_client(
                    client_id, {"type": "error", "error": "消息不能为空"}
                )
                return

            # P4: 配置读取含同步文件 IO（agents.json，TTL 过期后首个调用触发读盘），
            # 卸载到共享有界 IO 池执行（与 handlers/chat.py:135 同款方案），避免卡事件循环。
            # 保留 get_agent_config 模块级名称绑定（tests 以 monkeypatch 该名注入用例）。
            agent_config = await run_io(get_agent_config, agent_id)
            if not agent_config:
                await self.ws_manager.send_to_client(
                    client_id, {"type": "error", "error": f"Agent '{agent_id}' 不存在"}
                )
                return

            memory_mgr = get_memory_manager()
            context_mgr = get_context_manager()
            llm = get_llm_client_for_agent(agent_config)

            if session_id:
                if not context_mgr.get_session(session_id):
                    # 会话不存在：agent-{id} 模式自动创建（对齐历史读取键），否则报错
                    if session_id == f"agent-{agent_id}":
                        session_id = self._ensure_agent_session(
                            context_mgr, agent_id, agent_config
                        )
                    else:
                        await self.ws_manager.send_to_client(
                            client_id, {"type": "error", "error": f"会话 '{session_id}' 不存在"}
                        )
                        return
            else:
                # 无 session_id 时默认使用 agent-{id} 会话，与前端历史读取键一致
                session_id = self._ensure_agent_session(context_mgr, agent_id, agent_config)

            context_mgr.add_message(session_id=session_id, role="user", content=user_message)

            memory_context = await retrieve_memory_context(
                agent_config, memory_mgr, user_message, session_id
            )

            messages = build_messages(
                agent_config=agent_config,
                context_mgr=context_mgr,
                session_id=session_id,
                user_message=user_message,
                memory_context=memory_context,
            )

            response = await llm.chat(messages=messages, stream=False)

            context_mgr.add_message(
                session_id=session_id, role="assistant", content=response.content
            )

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
        finally:
            self._cancel_flags.pop(client_id, None)

    async def _handle_chat_stream(self, client_id: str, message: Dict[str, Any]):
        """处理流式聊天消息"""
        from server.dependencies import get_context_manager, get_memory_manager
        from server.chat_helpers import get_agent_config, get_llm_client_for_agent, retrieve_memory_context
        from server.prompt_builder import build_messages

        # E4: 提前初始化，保证 except 分支可安全引用（早期异常时为空串，不触发补写）
        full_response = ""

        try:
            agent_id = message.get("agent_id", "default")
            session_id = message.get("session_id")
            user_message = message.get("message", "")

            if not user_message:
                await self.ws_manager.send_to_client(
                    client_id, {"type": "error", "error": "消息不能为空"}
                )
                return

            # 获取配置（P4: run_io 卸载同步文件 IO，与 _handle_chat 同款方案）
            agent_config = await run_io(get_agent_config, agent_id)
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
                if not context_mgr.get_session(session_id):
                    # 会话不存在：agent-{id} 模式自动创建（对齐历史读取键），否则报错
                    if session_id == f"agent-{agent_id}":
                        session_id = self._ensure_agent_session(
                            context_mgr, agent_id, agent_config
                        )
                    else:
                        await self.ws_manager.send_to_client(
                            client_id, {"type": "error", "error": f"会话 '{session_id}' 不存在"}
                        )
                        return
            else:
                # 无 session_id 时默认使用 agent-{id} 会话，与前端历史读取键一致
                session_id = self._ensure_agent_session(context_mgr, agent_id, agent_config)

            # 发送会话ID
            await self.ws_manager.send_to_client(
                client_id, {"type": "session_info", "session_id": session_id}
            )

            # 添加用户消息
            context_mgr.add_message(session_id=session_id, role="user", content=user_message)

            # 检索记忆
            memory_context = await retrieve_memory_context(
                agent_config, memory_mgr, user_message, session_id
            )

            # 构建消息列表
            messages = build_messages(
                agent_config=agent_config,
                context_mgr=context_mgr,
                session_id=session_id,
                user_message=user_message,
                memory_context=memory_context,
            )

            # 流式响应（full_response 已在 try 前初始化，供取消/异常路径补写半截回复）
            self._cancel_flags[client_id] = False

            async for chunk in llm.stream_chat(
                messages=messages,
                temperature=agent_config.get("temperature", 0.7),
                max_tokens=agent_config.get("max_tokens", 4096),
            ):
                if self._cancel_flags.get(client_id, False):
                    # E4: 取消时已生成的半截回复补写入库，避免「用户问了没回答」断层。
                    # 先发 cancelled 帧再补写：若发送失败落入 except 分支，由 except 补写，不重复。
                    await self.ws_manager.send_to_client(
                        client_id, {"type": "cancelled", "timestamp": datetime.now().isoformat()}
                    )
                    if full_response:
                        context_mgr.add_message(
                            session_id=session_id,
                            role="assistant",
                            content=full_response + "\n\n[已打断]",
                        )
                    return

                if not chunk:
                    continue

                # W4: 对齐 HTTP SSE 契约（api/routers/chat.py generate_stream）——
                # stream_chat 可能产出 dict 分帧（thinking/content/tool_calls）。
                # thinking 帧以相同字段（type/content）转发给 WS 客户端；内容帧仍以
                # chat_chunk 外发，既有帧契约不变。旧格式（str）行为保持原样。
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type")
                    if chunk_type == "thinking":
                        await self.ws_manager.send_to_client(
                            client_id,
                            {"type": "thinking", "content": chunk.get("content", "")},
                        )
                    elif chunk_type == "tool_calls":
                        # WS 聊天流未启用工具链（stream_chat 未传 tools），防御性跳过
                        logger.debug(f"WS 聊天流忽略 tool_calls 帧: {chunk.get('tool_calls', [])}")
                    else:
                        content = chunk.get("content", "")
                        if content:
                            full_response += content
                            await self.ws_manager.send_to_client(
                                client_id, {"type": "chat_chunk", "content": content}
                            )
                elif isinstance(chunk, str):
                    full_response += chunk
                    await self.ws_manager.send_to_client(
                        client_id, {"type": "chat_chunk", "content": chunk}
                    )

            # 保存完整响应
            if full_response:
                context_mgr.add_message(
                    session_id=session_id, role="assistant", content=full_response
                )
                # E4: 已完整入库即置空，防止后续 chat_done 发送失败时 except 分支重复补写
                full_response = ""

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
            # E4: 流中途异常时补写已生成的半截回复，避免「用户问了没回答」断层。
            # full_response 非空意味着 context_mgr/session_id 必已就绪；先补写再发
            # error 帧（连接已断时发送会抛异常，补写仍需完成）。
            if full_response:
                context_mgr.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=full_response + "\n\n[已中断]",
                )
            await self.ws_manager.send_to_client(client_id, {"type": "error", "error": str(e)})
        finally:
            self._cancel_flags.pop(client_id, None)

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

        # W1: agent_id 落入连接 metadata 并自动订阅 agent:{id} alarm 频道。
        # 前端从不显式发 subscribe，alarm 推送（push_alarm_to_agent → broadcast_to_channel）
        # 依赖此自动订阅触达前端提醒 UI。字段缺失时行为不变（向后兼容）。
        agent_id = message.get("agent_id")
        if agent_id:
            connection = self.ws_manager.connections.get(client_id)
            if connection is not None:
                old_agent_id = connection.metadata.get("agent_id")
                new_channel = f"agent:{agent_id}"
                old_channel = f"agent:{old_agent_id}" if old_agent_id else None
                # 换绑到不同 agent：先退订旧 alarm 频道，避免跨 agent 串音
                if old_channel and old_channel != new_channel and connection.is_subscribed(old_channel):
                    self.ws_manager.unsubscribe_from_channel(client_id, old_channel)
                connection.metadata["agent_id"] = agent_id
                self.ws_manager.subscribe_to_channel(client_id, new_channel)


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
