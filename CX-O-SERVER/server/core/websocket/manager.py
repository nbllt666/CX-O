"""WebSocket 连接与消息管理器——管理客户端连接生命周期、消息路由与广播。"""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, Optional, Set

from fastapi import WebSocket

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


class WebSocketConnection:
    """WebSocket 连接封装"""

    def __init__(self, websocket: WebSocket, client_id: str, metadata: Optional[Dict] = None):
        self.websocket = websocket
        self.client_id = client_id
        self.metadata = metadata or {}
        self.connected_at = datetime.now()
        self.last_activity = datetime.now()
        self.subscriptions: Set[str] = set()  # 订阅的频道
        # R9-01 重连串扰防护：连接代际（由 manager.connect 在锁内递增赋值）。
        # 同 client_id 重连时代际单调推进，旧端点 finally 携带旧代际调用
        # disconnect 时将被代际校验拦下，不得拆毁新会话。
        self.generation: int = 0
        # 二进制帧 error 帧限频状态（monotonic 时间戳，每连接独立）
        self._last_unsupported_frame_error_ts: float = 0.0

    async def send(self, data: Dict[str, Any]):
        """发送消息"""
        try:
            await self.websocket.send_json(data)
            self.last_activity = datetime.now()
        except Exception as e:
            logger.error(f"发送消息失败 {self.client_id}: {e}")
            raise

    async def receive(self) -> Dict[str, Any]:
        """接收消息

        E3 修复：不再使用 receive_json()——畸形 JSON 会抛 JSONDecodeError、
        二进制帧会抛 KeyError 直接穿透 /ws/{agent_id}、/ws、/ws/chat 三个端点。
        改为原生 receive() 按帧类型取 text/bytes 后手动 json.loads：
        解析失败（含非 dict 的合法 JSON）记 debug 日志并跳过，循环取下一帧；
        WebSocketDisconnect 不捕获，连接关闭时正常向上传播。
        """
        while True:
            raw = await self.websocket.receive()
            if "text" in raw:
                payload = raw["text"]
                is_binary = False
            elif "bytes" in raw:
                payload = raw["bytes"]
                is_binary = True
            else:
                # 其余未知控制帧兜底跳过（断连由 starlette 以 WebSocketDisconnect 抛出）
                continue
            # R9-01 配套：任何到达的数据帧均视为活跃并刷新 last_activity——
            # 此前二进制/畸形帧跳过路径不刷新，活跃客户端会被超时清理误杀
            self.last_activity = datetime.now()
            try:
                data = json.loads(payload)
            except (ValueError, TypeError):
                preview = payload if isinstance(payload, str) else repr(payload[:64])
                logger.debug(f"收到非 JSON 帧，已跳过 {self.client_id}: {str(preview)[:100]}")
                if is_binary:
                    # 二进制帧不支持：限频回发 error 帧（每连接每 5 秒最多 1 条，
                    # 防畸形帧洪泛放大流量）
                    await self._send_unsupported_frame_error()
                continue
            if not isinstance(data, dict):
                # 保持返回契约 Dict[str, Any]：合法 JSON 标量/数组同样跳过
                logger.debug(f"收到非对象 JSON 帧，已跳过 {self.client_id}: {type(data).__name__}")
                continue
            return data

    # 二进制帧 error 帧限频间隔（秒）：每连接每 5 秒最多回发 1 条
    UNSUPPORTED_FRAME_ERROR_INTERVAL = 5.0

    async def _send_unsupported_frame_error(self):
        """二进制帧 error 帧限频回发：防畸形帧洪泛在收帧路径上放大发送流量。"""
        now = time.monotonic()
        if now - self._last_unsupported_frame_error_ts < self.UNSUPPORTED_FRAME_ERROR_INTERVAL:
            return
        self._last_unsupported_frame_error_ts = now
        try:
            await self.send({
                "type": "error",
                "code": "UNSUPPORTED_FRAME",
                "message": "不支持二进制帧",
            })
        except Exception as e:
            logger.debug(f"UNSUPPORTED_FRAME error 帧回发失败 {self.client_id}: {e}")

    def subscribe(self, channel: str):
        """订阅频道"""
        self.subscriptions.add(channel)

    def unsubscribe(self, channel: str):
        """取消订阅"""
        self.subscriptions.discard(channel)

    def is_subscribed(self, channel: str) -> bool:
        """是否订阅了频道"""
        return channel in self.subscriptions


class WebSocketManager:
    """WebSocket 连接管理器

    管理所有 WebSocket 连接，支持广播、分组、订阅等功能
    """

    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self.channels: Dict[str, Set[str]] = {}  # 频道 -> 客户端ID集合
        self.message_handlers: Dict[str, Callable] = {}
        self._action_handlers: Dict[str, Callable] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._background_tasks: Set[asyncio.Task] = set()
        self._running = False
        self._offline_callback: Optional[Callable] = None
        self._agent_timeouts: Dict[str, int] = {}  # agent_id -> timeout seconds
        self._llm_count: int = 0
        # R9-01 重连串扰防护：client_id -> 当前登记连接代际。
        # 代际取自全局单调序列 _generation_seq（而非 per-client +1），
        # 真实断开时回收条目也不会产生 ABA 复用，历史残留 disconnect
        # 无法再命中新连接；字典规模始终与活跃连接同阶，不无界增长。
        self._generations: Dict[str, int] = {}
        self._generation_seq: int = 0
        # E6 修复: 单一保护机制收口——同一组共享结构（connections/channels）此前被
        # asyncio.Lock 与 threading.Lock 两把锁分别守护（异步路径用前者、同步订阅路径
        # 用后者），跨锁竞态下仍可能互踩。统一为一把 threading.RLock：
        # - 同步方法 subscribe/unsubscribe 无法 await asyncio.Lock，必须用线程锁；
        # - 异步路径的各临界区均为无 await 的快速 dict 拷贝/增删（快照后再在锁外 send），
        #   阻塞式线程锁开销可忽略；
        # - 选用 RLock 允许重入（disconnect 持锁调用 _remove_from_channel 等内部复用
        #   场景天然安全），对外方法签名与语义保持不变。
        self._lock = threading.RLock()

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        """追踪后台任务，防止被GC回收；任务完成后自动从集合中移除"""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def connect(
        self, websocket: WebSocket, client_id: Optional[str] = None, metadata: Optional[Dict] = None,
        send_connected: bool = True
    ) -> WebSocketConnection:
        """接受新连接

        BUG-B07 修复: 在锁内完成 ``self.connections`` 写入,保证与
        ``disconnect``/``broadcast`` 的并发安全。
        """
        await websocket.accept()

        if not client_id:
            import uuid

            client_id = str(uuid.uuid4())

        connection = WebSocketConnection(websocket, client_id, metadata)
        # E6 修复: 统一 RLock；临界区内仅做 dict 写入，不含 await。
        with self._lock:
            # R9-01 重连串扰防护：分配全局单调代际并登记，同 id 旧连接被
            # 新连接覆盖（代际已推进，旧端点 disconnect 将被代际校验拦下）。
            old_connection = self.connections.get(client_id)
            self._generation_seq += 1
            connection.generation = self._generation_seq
            self._generations[client_id] = connection.generation
            self.connections[client_id] = connection

        if old_connection is not None:
            # 检测到同 client_id 旧连接：先 close 旧 socket（抑制异常），
            # 防旧连接继续收发串扰；旧端点收帧循环随即断开，其 finally 携带
            # 旧代际调用 disconnect 时会被代际校验拦下，不拆毁本新会话。
            logger.info(f"检测到同 client_id 旧连接，已关闭旧 socket 防串扰: {client_id}")
            try:
                await old_connection.websocket.close(code=1000)
            except Exception as e:
                logger.debug(f"关闭旧连接失败（可能已关闭）: {client_id}: {e}")

        # per-client 并发化：懒创建该客户端的独立 VAD/AudioStream 处理器实例，
        # 后续 /ws/live、dual_stream 会话按 client_id 取自己的实例，互不串扰。
        try:
            from server.services.vad_processor import get_audio_stream_processor
            get_audio_stream_processor(client_id)
        except Exception as e:
            logger.warning(f"初始化客户端音频处理器失败 {client_id}: {e}")

        logger.info(f"WebSocket 连接已建立: {client_id}, 当前连接数: {len(self.connections)}")

        if send_connected:
            await connection.send(
                {"type": "connected", "client_id": client_id, "timestamp": datetime.now().isoformat()}
            )

        return connection

    async def disconnect(self, client_id: str, generation: Optional[int] = None):
        """断开连接

        BUG-B07 修复: 在锁内完成 ``self.connections`` / ``self.channels``
        的修改,避免与 ``broadcast``/``subscribe_to_channel`` 的并发竞争。

        R9-01 代际校验: 调用方（/ws 端点 finally）传入其连接的 generation，
        仅当与当前登记代际一致才执行清理——同 id 重连后，旧端点 finally
        携带旧代际到达时直接跳过，不得拆毁新会话/新会话的频道成员。
        generation 为 None（内部清理路径/外部踢出等未携带代际的调用）时，
        以当前登记连接自身的代际为准——等价于"清理当前登记连接"，保持
        既有语义不变。
        """
        with self._lock:
            connection = self.connections.get(client_id)
            if connection is None:
                return

            current_generation = self._generations.get(client_id, 0)
            effective_generation = connection.generation if generation is None else generation
            if effective_generation != current_generation:
                logger.info(
                    f"跳过过期 disconnect（代际不匹配，不拆毁新会话）: {client_id}, "
                    f"gen={effective_generation} != current={current_generation}"
                )
                return

            # 代际校验通过 → 正式移除连接并回收代际登记（代际取自全局
            # 单调序列，回收后新连接拿到更大代际，历史残留 disconnect
            # 无法再命中，无 ABA 复用风险）
            del self.connections[client_id]
            self._generations.pop(client_id, None)

            # 从所有频道中移除（代际校验通过后才执行，防误删新连接成员）
            for channel in list(connection.subscriptions):
                self._remove_from_channel(channel, client_id)

        logger.info(f"WebSocket 连接已断开: {client_id}, 当前连接数: {len(self.connections)}")

        # H4 修复：显式关闭底层 WebSocket（锁外执行，幂等无害）。
        # 超时清理/踢出的连接此前从不调用 close()，客户端侧 TCP 保持半开，
        # 形成假在线僵尸连接（收不到推送也无感知）。已关闭的连接再 close
        # 会抛异常，统一吞掉即可。
        try:
            await connection.websocket.close(code=1000)
        except Exception as e:
            logger.debug(f"关闭底层 WebSocket 失败（可能已关闭）: {client_id}: {e}")

        # 清理该客户端的双流式语音会话（根治孤儿 pipeline 泄漏：
        # 不清理则 LLM+TTS 流水线持续运行占用资源并向空连接推流，
        # 多轮累积致 TTS 服务并发排队、端到端延迟暴涨）
        try:
            from server.handlers.audio import cleanup_dual_stream_session
            await cleanup_dual_stream_session(client_id)
        except Exception as e:
            logger.warning(f"清理双流式会话失败 {client_id}: {e}")

        # 释放该客户端的 per-client 语音实例（VAD/AudioStream / ASR 流式会话 /
        # 打断模块），仅清理当前客户端，不影响其它客户端与默认单例。
        try:
            from server.services.vad_processor import release_audio_stream_processor
            from server.services.asr_interrupt import release_asr_interrupt_module
            from server.services.agent_interrupt_user import release_agent_interrupt_module
            release_audio_stream_processor(client_id)
            try:
                from server.services.asr_service import get_asr_service
                await get_asr_service().release_streaming_session(client_id)
            except Exception:
                pass
            release_asr_interrupt_module(client_id)
            release_agent_interrupt_module(client_id)
        except Exception as e:
            logger.warning(f"释放客户端音频实例失败 {client_id}: {e}")

    async def send_to_client(self, client_id: str, message: Dict[str, Any]):
        """发送消息给指定客户端

        BUG-B07 修复: 在锁内读取连接并复制出引用,然后在锁外执行 await send,
        避免长时间持锁阻塞其他协程。
        """
        with self._lock:
            connection = self.connections.get(client_id)
        if connection is not None:
            # isEnabledFor 门控：send_to_client 每帧调用（voice.dual_stream 热路径），
            # 避免每帧对 message.get('type') 急切求值；仅 DEBUG 才做 DIAG-SEND 诊断。
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[DIAG-SEND] sending type=%s to client_id=%s", message.get('type'), client_id)
            await connection.send(message)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("[DIAG-SEND] sent type=%s to client_id=%s", message.get('type'), client_id)
        else:
            logger.warning(f"[DIAG-SEND] connection is None for client_id={client_id}, type={message.get('type')}")

    async def send_message(self, client_id: str, message: Dict[str, Any]):
        """发送消息给指定客户端（send_to_client 的别名）"""
        await self.send_to_client(client_id, message)

    # A6: 单连接发送超时（秒）——慢客户端不再阻塞整个广播
    SEND_TIMEOUT = 5.0

    @staticmethod
    async def _send_with_timeout(client_id: str, connection, message, timeout: float = 5.0):
        """带超时的单连接发送：成功返回 None，失败/超时返回 client_id（供调用方清理）。"""
        try:
            await asyncio.wait_for(connection.send(message), timeout=timeout)
            return None
        except Exception:
            return client_id

    async def broadcast(self, message: Dict[str, Any], exclude: Optional[str] = None):
        """广播消息给所有客户端

        先对 `self.connections` 进行快照后再迭代，避免在发送过程中因
        `disconnect` 触发 `RuntimeError: dictionary changed size during iteration`。
        断连清理通过延迟异步任务执行。

        BUG-B07 修复: 快照在锁内完成,确保一致视图。
        A6 修复: 逐个 await 改为 gather 并发发送 + 单连接超时，一个慢客户端
        不再阻塞整个广播。
        """
        # 1) 迭代前在锁内对字典进行快照,避免快照过程中字典被改
        with self._lock:
            connections_snapshot = list(self.connections.items())

        # R9-01: 记录发送目标连接的代际，清理时回传 disconnect 做代际校验
        generation_by_client = {cid: conn.generation for cid, conn in connections_snapshot}

        results = await asyncio.gather(
            *[
                self._send_with_timeout(client_id, connection, message, self.SEND_TIMEOUT)
                for client_id, connection in connections_snapshot
                if client_id != exclude
            ]
        )
        disconnected = [client_id for client_id in results if client_id]

        # 2) 清理断开的连接：延迟到下一次事件循环，避免在当前调用栈中修改字典
        #    （携带发送失败时的连接代际，防清理期间同 id 重连后误拆新连接）
        if disconnected:
            pairs = [(cid, generation_by_client.get(cid)) for cid in disconnected]
            self._track_background_task(asyncio.create_task(self._cleanup_disconnected(pairs)))

    async def _cleanup_disconnected(self, disconnected: list):
        """延迟清理已断开的连接（异步任务中执行）

        disconnected 为 (client_id, generation) 二元组列表：generation 为
        发送失败时目标连接的代际，供 disconnect 做代际校验（R9-01）。
        """
        for client_id, generation in disconnected:
            try:
                await self.disconnect(client_id, generation=generation)
            except Exception as e:
                logger.debug(f"清理断开连接 {client_id} 失败: {e}")

    async def broadcast_external_event(self, source: str, event_type: str, title: str, body: str):
        message = {
            "event": "external_event",
            "data": {
                "source": source,
                "type": event_type,
                "title": title,
                "body": body,
            }
        }
        await self.broadcast(message)

    async def broadcast_to_channel(self, channel: str, message: Dict[str, Any]):
        """广播消息给频道内所有客户端

        先对频道订阅者集合及全局连接字典进行快照后再迭代，
        避免在发送过程中因 `disconnect` 触发字典修改异常。
        断连清理通过延迟异步任务执行。

        BUG-B07 修复: 快照在锁内完成,确保一致视图。
        """
        # 1) 迭代前在锁内对频道成员和连接字典分别做快照
        with self._lock:
            members_snapshot = list(self.channels.get(channel, set()))
            connections_snapshot = dict(self.connections)

        # R9-01: 记录发送目标连接的代际，清理时回传 disconnect 做代际校验
        generation_by_client = {cid: conn.generation for cid, conn in connections_snapshot.items()}

        # A6 修复: gather 并发发送 + 单连接超时（与 broadcast 同口径）
        results = await asyncio.gather(
            *[
                self._send_with_timeout(
                    client_id, connections_snapshot[client_id], message, self.SEND_TIMEOUT
                )
                for client_id in members_snapshot
                if connections_snapshot.get(client_id) is not None
            ]
        )
        disconnected = [client_id for client_id in results if client_id]

        # 2) 清理断开的连接：延迟到下一次事件循环
        #    （携带发送失败时的连接代际，防清理期间同 id 重连后误拆新连接）
        if disconnected:
            pairs = [(cid, generation_by_client.get(cid)) for cid in disconnected]
            self._track_background_task(asyncio.create_task(self._cleanup_disconnected(pairs)))

    def subscribe_to_channel(self, client_id: str, channel: str):
        """订阅频道

        BUG-B-M4 修复: 使用 threading.Lock 保护对共享 self.channels /
        self.connections 的读写,避免多线程并发调用时数据竞争。
        """
        with self._lock:
            if client_id not in self.connections:
                return

            if channel not in self.channels:
                self.channels[channel] = set()

            self.channels[channel].add(client_id)
            self.connections[client_id].subscribe(channel)

        logger.debug(f"客户端 {client_id} 订阅频道: {channel}")

    def unsubscribe_from_channel(self, client_id: str, channel: str):
        """取消订阅频道

        BUG-B-M4 修复: 使用 threading.Lock 保护对共享 self.channels /
        self.connections 的读写,避免多线程并发调用时数据竞争。
        """
        with self._lock:
            if client_id in self.connections:
                self.connections[client_id].unsubscribe(channel)

            self._remove_from_channel(channel, client_id)

        logger.debug(f"客户端 {client_id} 取消订阅频道: {channel}")

    def _remove_from_channel(self, channel: str, client_id: str):
        """从频道中移除客户端

        BUG-B07 修复 / E6 收口: 由调用方持统一 threading.RLock 后调用
        （``disconnect``/``unsubscribe_from_channel`` 均在锁内调用本方法），
        确保与 ``broadcast_to_channel`` 的快照读不会并发。
        """
        if channel in self.channels:
            self.channels[channel].discard(client_id)
            if not self.channels[channel]:
                del self.channels[channel]

    def register_handler(self, message_type: str, handler: Callable):
        """注册消息处理器（基于 type 路由）"""
        self.message_handlers[message_type] = handler
        logger.debug(f"注册消息处理器: {message_type}")

    def register_action_handler(self, action: str, handler: Callable):
        """注册 action 处理器（基于 action 路由）"""
        self._action_handlers[action] = handler
        logger.debug(f"注册 action 处理器: {action}")

    def get_handler(self, action: str) -> Optional[Callable]:
        """获取 action 对应的处理器"""
        return self._action_handlers.get(action)

    def set_offline_callback(self, callback: Callable):
        """设置离线回调函数

        当连接超时离线时调用，用于保存上下文到长期记忆
        callback(agent_id: str) -> None
        """
        self._offline_callback = callback
        logger.debug("已设置离线回调函数")

    def set_agent_timeout(self, agent_id: str, timeout: int):
        """设置 Agent 的离线超时时间"""
        self._agent_timeouts[agent_id] = timeout
        logger.debug(f"设置 Agent {agent_id} 离线超时: {timeout}秒")

    async def handle_message(self, client_id: str, message: Dict[str, Any]):
        """处理收到的消息（基于 type 路由，action 回退）

        路由优先级：
        1. type 字段匹配 message_handlers → 走 type 路由（向后兼容）
        2. action 字段存在 → 走 handle_action_message（voice.dual_stream 等）
        3. 都不匹配 → 报错"未知消息类型"
        """
        msg_type = message.get("type", "unknown")

        if msg_type in self.message_handlers:
            try:
                await self.message_handlers[msg_type](client_id, message)
            except Exception as e:
                logger.error(f"处理消息失败 {msg_type}: {e}")
                await self.send_to_client(
                    client_id, {"type": "error", "error": f"处理消息失败: {str(e)}"}
                )
        elif "action" in message:
            # action 回退：type 不匹配但有 action 字段，走 action 路由
            # 支持 voice.dual_stream / chat.message / chat.stream 等 action-based 协议
            await self.handle_action_message(client_id, message)
        else:
            logger.warning(f"未知消息类型: {msg_type}")
            await self.send_to_client(
                client_id, {"type": "error", "error": f"未知消息类型: {msg_type}"}
            )

    async def handle_action_message(self, client_id: str, message: Dict[str, Any]):
        """处理收到的消息（基于 action 路由）

        M 修复：连接读取纳入 ``self._lock`` 快照；无连接时告警直接返回——
        连接不存在无处回发错误帧，且此前会把 ``None`` 作为 websocket 传入 handler。
        """
        action = message.get("action", "")
        if action in self._action_handlers:
            handler = self._action_handlers[action]
            with self._lock:
                connection = self.connections.get(client_id)
            if connection is None:
                logger.warning(
                    f"[DIAG-ACTION] connection is None for client_id={client_id}, action={action}"
                )
                return
            try:
                await handler(connection.websocket, message, client_id)
            except Exception as e:
                # E2a 修复：与 type 路由的 try/except 对称——handler 异常不再
                # 穿透断连端点；留痕后尝试向该 client 回发 error 帧，不向上抛。
                logger.exception(f"action 处理失败 {action} (client={client_id}): {e}")
                try:
                    await self.send_to_client(
                        client_id,
                        {"type": "error", "data": {"message": "action 处理失败"}},
                    )
                except Exception as send_err:
                    logger.debug(f"action 错误帧回发失败 client={client_id}: {send_err}")
        else:
            logger.warning(f"未知 action: {action}")
            await self.send_to_client(
                client_id, {"type": "error", "error": f"未知 action: {action}"}
            )

    async def start_cleanup_task(self, interval_seconds: int = 300):
        """启动清理任务"""
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_seconds))
        logger.info("WebSocket 清理任务已启动")

    async def stop_cleanup_task(self):
        """停止清理任务"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("WebSocket 清理任务已停止")

    async def _cleanup_loop(self, interval_seconds: int):
        """清理循环"""
        while self._running:
            try:
                await self._cleanup_inactive_connections()
            except Exception as e:
                logger.error(f"清理连接失败: {e}")

            await asyncio.sleep(interval_seconds)

    async def _cleanup_inactive_connections(self):
        """清理不活跃的连接，并触发离线保存

        BUG-B07 修复: 迭代 ``self.connections`` / ``self._agent_timeouts`` 时
        在锁内拷贝,避免迭代过程中字典被改。
        """
        from datetime import timedelta

        now = datetime.now()

        with self._lock:
            connections_snapshot = list(self.connections.items())
            agent_timeouts_snapshot = dict(self._agent_timeouts)
            offline_callback = self._offline_callback

        inactive = []
        for client_id, connection in connections_snapshot:
            agent_id = connection.metadata.get("agent_id", "default")
            timeout_seconds = agent_timeouts_snapshot.get(agent_id, 1800)
            timeout = timedelta(seconds=timeout_seconds)

            if now - connection.last_activity > timeout:
                # R9-01: 快照时捕获连接代际，disconnect 校验防超时清理与
                # 同 id 重连竞态下误拆新连接
                inactive.append((client_id, agent_id, connection.generation))

        for client_id, agent_id, generation in inactive:
            logger.info(f"连接超时离线: {client_id}, agent={agent_id}")
            await self.disconnect(client_id, generation=generation)

            if offline_callback:
                try:
                    await offline_callback(agent_id)
                except Exception as e:
                    logger.error(f"离线回调失败 {agent_id}: {e}")

    def increment_llm_count(self):
        self._llm_count += 1

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_connections": len(self.connections),
            "total_channels": len(self.channels),
            "channels": {channel: len(clients) for channel, clients in self.channels.items()},
            "llm_count": self._llm_count,
            "client_count": len(self.connections),
        }


# 全局 WebSocket 管理器实例
_websocket_manager: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """获取全局 WebSocket 管理器实例"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
