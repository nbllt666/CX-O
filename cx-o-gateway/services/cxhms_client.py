"""
CXHMS WebSocket 客户端
"""
import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Optional
import websockets
from websockets.client import WebSocketClientProtocol
from websockets.protocol import State

from protocol.message import create_request, MessageType

logger = logging.getLogger(__name__)


class CXHMSClient:
    def __init__(self, url: str, pool_size: int = 5):
        self._url = url
        self._pool_size = pool_size
        self._connections: list[WebSocketClientProtocol] = []
        self._connection_available = asyncio.Event()
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._running = False
        self._receive_tasks: list[asyncio.Task] = []
        self._reconnect_interval = 5
        self._heartbeat_interval = 30
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._connection_lock = asyncio.Lock()

    async def connect(self):
        self._running = True
        for i in range(self._pool_size):
            try:
                conn = await websockets.connect(self._url)
                self._connections.append(conn)
                task = asyncio.create_task(self._receive_loop(conn, i))
                self._receive_tasks.append(task)
            except Exception as e:
                logger.error(f"Failed to connect connection {i}: {e}")
        
        if self._connections:
            self._connection_available.set()
        
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"Connected to CXHMS with {len(self._connections)} connections")

    async def disconnect(self):
        self._running = False
        self._connection_available.clear()
        
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        
        for task in self._receive_tasks:
            task.cancel()
        
        for conn in self._connections:
            await conn.close()
        
        self._connections.clear()
        self._receive_tasks.clear()
        logger.info("Disconnected from CXHMS")

    async def _receive_loop(self, conn: WebSocketClientProtocol, conn_id: int):
        try:
            async for message in conn:
                try:
                    data = json.loads(message)
                    request_id = data.get("request_id")
                    
                    logger.debug(f"Received message from CXHMS: request_id={request_id}, data={data}")
                    
                    if request_id and request_id in self._pending_requests:
                        pending = self._pending_requests.pop(request_id)
                        logger.debug(f"Found pending request for {request_id}, type={type(pending)}")
                        
                        # 检查是 Future 还是 callback function
                        if callable(pending):
                            # Stream callback - 可能是 async 或 sync
                            callback = pending
                            logger.debug(f"Calling stream callback with data: {data}")
                            if asyncio.iscoroutinefunction(callback):
                                await callback(data)
                            else:
                                callback(data)
                        else:
                            # Future
                            future = pending
                            if not future.done():
                                future.set_result(data)
                    else:
                        logger.debug(f"Received message without pending request: {data}")
                        
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from CXHMS connection {conn_id}")
                    
        except websockets.ConnectionClosed:
            logger.warning(f"CXHMS connection {conn_id} closed")
            await self._reconnect(conn_id)
        except Exception as e:
            logger.error(f"Error in receive loop {conn_id}: {e}")

    async def _reconnect(self, conn_id: int):
        while self._running:
            try:
                await asyncio.sleep(self._reconnect_interval)
                conn = await websockets.connect(self._url)
                while len(self._connections) <= conn_id:
                    self._connections.append(None)
                self._connections[conn_id] = conn

                task = asyncio.create_task(self._receive_loop(conn, conn_id))
                while len(self._receive_tasks) <= conn_id:
                    self._receive_tasks.append(None)
                self._receive_tasks[conn_id] = task

                logger.info(f"Reconnected CXHMS connection {conn_id}")
                break
            except Exception as e:
                logger.error(f"Reconnect failed for {conn_id}: {e}")

    async def _heartbeat_loop(self):
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)
                for conn in self._connections:
                    if conn.state == State.OPEN:
                        await conn.send(json.dumps({"type": "ping", "timestamp": time.time()}))
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _get_connection(self) -> Optional[WebSocketClientProtocol]:
        async with self._connection_lock:
            for conn in self._connections:
                if conn and conn.state == State.OPEN:
                    return conn
            return None

    async def request(self, action: str, data: dict[str, Any], timeout: float = 30.0) -> dict:
        request_id = str(uuid.uuid4())
        message = create_request(action, data, request_id)

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        async with self._connection_lock:
            conn = None
            for c in self._connections:
                if c and c.state == State.OPEN:
                    conn = c
                    break

            if not conn:
                self._pending_requests.pop(request_id, None)
                raise ConnectionError("No available connection to CXHMS")

            try:
                await conn.send(json.dumps(message))
            except websockets.ConnectionClosed:
                self._pending_requests.pop(request_id, None)
                raise ConnectionError("Connection closed during send")

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Request {action} timed out")
        except Exception as e:
            self._pending_requests.pop(request_id, None)
            raise

    async def stream(self, action: str, data: dict[str, Any], callback: Callable[[dict], None], timeout: float = 60.0):
        request_id = str(uuid.uuid4())
        message = create_request(action, data, request_id)

        logger.info(f"Stream request: action={action}, request_id={request_id}")

        stream_complete = asyncio.Event()

        async def handle_stream_response(response: dict):
            logger.debug(f"Stream handler received response: {response}")
            if response.get("request_id") == request_id:
                logger.debug(f"Request ID matches, calling callback")
                if asyncio.iscoroutinefunction(callback):
                    await callback(response)
                else:
                    callback(response)
                if response.get("is_final", False) or response.get("type") == "error":
                    logger.debug("Stream complete")
                    stream_complete.set()

        async with self._connection_lock:
            conn = None
            for c in self._connections:
                if c and c.state == State.OPEN:
                    conn = c
                    break

            if not conn:
                raise ConnectionError("No available connection to CXHMS")

            self._pending_requests[request_id] = handle_stream_response
            logger.info(f"Registered stream handler for request_id={request_id}")

            try:
                logger.info(f"Sending stream request to CXHMS: {message}")
                await conn.send(json.dumps(message))
            except websockets.ConnectionClosed:
                self._pending_requests.pop(request_id, None)
                raise ConnectionError("Connection closed during send")

        try:
            logger.info("Waiting for stream to complete...")
            await asyncio.wait_for(stream_complete.wait(), timeout=timeout)
            logger.info("Stream completed successfully")
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Stream {action} timed out")
        finally:
            self._pending_requests.pop(request_id, None)

    async def send_message(
        self,
        message: str,
        context: list = None,
        stream: bool = False,
        agent_id: str = "default"
    ) -> dict:
        """
        发送消息到 CXHMS 的便捷方法
        
        Args:
            message: 用户消息
            context: 对话上下文（消息列表）
            stream: 是否使用流式响应
            agent_id: Agent ID
            
        Returns:
            dict: 响应结果，包含 content/text 字段
        """
        if context is None:
            context = []
        
        messages = context + [{"role": "user", "content": message}]
        
        data = {
            "messages": messages,
            "agent_id": agent_id,
            "stream": stream
        }
        
        if stream:
            result = {"content": "", "text": "", "is_final": False}
            
            async def handle_stream(response: dict):
                content = response.get("content", response.get("text", ""))
                if content:
                    result["content"] += content
                    result["text"] += content
                if response.get("is_final", False):
                    result["is_final"] = True
            
            await self.stream("chat", data, handle_stream)
            return result
        else:
            response = await self.request("chat", data)
            return {
                "content": response.get("content", response.get("text", "")),
                "text": response.get("content", response.get("text", "")),
                "success": response.get("success", True)
            }
