#!/usr/bin/env python3
"""
WebSocket管理器

功能：
- 管理WebSocket连接
- 流式响应推送
- 事件主动推送
"""

import json
import logging
from typing import Dict, Set, Optional
from datetime import datetime
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # 活跃连接
        self.active_connections: Dict[str, WebSocket] = {}
        
        # 会话ID到连接ID的映射
        self.session_to_connection: Dict[str, str] = {}
        
        # 连接ID计数器
        self._connection_counter = 0
    
    async def connect(
        self,
        websocket: WebSocket,
        session_id: Optional[str] = None
    ) -> str:
        """
        建立WebSocket连接
        
        Args:
            websocket: WebSocket连接
            session_id: 可选的会话ID
        
        Returns:
            connection_id: 连接ID
        """
        await websocket.accept()
        
        # 生成连接ID
        self._connection_counter += 1
        connection_id = f"conn_{self._connection_counter}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        # 存储连接
        self.active_connections[connection_id] = websocket
        
        # 关联会话
        if session_id:
            self.session_to_connection[session_id] = connection_id
        
        logger.info(f"WebSocket连接建立: connection_id={connection_id}, session_id={session_id}")
        
        return connection_id
    
    def disconnect(self, connection_id: str):
        """
        断开WebSocket连接
        
        Args:
            connection_id: 连接ID
        """
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            
            # 清理会话映射
            sessions_to_remove = [
                session_id for session_id, conn_id 
                in self.session_to_connection.items() 
                if conn_id == connection_id
            ]
            for session_id in sessions_to_remove:
                del self.session_to_connection[session_id]
            
            logger.info(f"WebSocket连接断开: connection_id={connection_id}")
    
    async def send_message(
        self,
        connection_id: str,
        message: dict,
        event: str = "message"
    ):
        """
        发送消息到指定连接
        
        Args:
            connection_id: 连接ID
            message: 消息内容（字典，会自动转为JSON）
            event: 事件类型
        """
        if connection_id not in self.active_connections:
            logger.warning(f"连接不存在: {connection_id}")
            return False
        
        try:
            websocket = self.active_connections[connection_id]
            
            # 构建消息
            full_message = {
                "event": event,
                "data": message,
                "timestamp": datetime.now().isoformat()
            }
            
            # 发送JSON消息
            await websocket.send_json(full_message)
            return True
        
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self.disconnect(connection_id)
            return False
    
    async def send_text(
        self,
        connection_id: str,
        text: str,
        is_final: bool = False
    ):
        """
        发送文本片段（用于流式输出）
        
        Args:
            connection_id: 连接ID
            text: 文本内容
            is_final: 是否是最后一个片段
        """
        return await self.send_message(
            connection_id,
            {"text": text, "is_final": is_final},
            event="text_chunk"
        )
    
    async def send_thinking(self, connection_id: str, data: dict = None):
        """
        发送思考状态
        """
        return await self.send_message(
            connection_id,
            data or {},
            event="thinking"
        )
    
    async def send_audio_start(
        self,
        connection_id: str,
        mime_type: str = "audio/wav",
        speech_id: str = None
    ):
        """
        发送音频流开始信号
        """
        return await self.send_message(
            connection_id,
            {"mime_type": mime_type, "speech_id": speech_id},
            event="audio_stream_start"
        )
    
    async def send_audio_chunk(
        self,
        connection_id: str,
        audio_data: bytes,
        is_effect: bool = False
    ):
        """
        发送音频片段
        """
        import base64
        
        return await self.send_message(
            connection_id,
            {
                "audio": base64.b64encode(audio_data).decode(),
                "is_effect": is_effect
            },
            event="audio_chunk"
        )
    
    async def send_action(
        self,
        connection_id: str,
        action_type: str,
        action_data: dict
    ):
        """
        发送动作指令
        """
        return await self.send_message(
            connection_id,
            {"type": action_type, **action_data},
            event="action"
        )
    
    async def send_external_event(
        self,
        connection_id: str,
        source: str,
        event_type: str,
        title: str,
        body: str
    ):
        """
        发送外部事件（如QQ消息、日程提醒等）
        """
        return await self.send_message(
            connection_id,
            {
                "source": source,
                "type": event_type,
                "title": title,
                "body": body
            },
            event="external_event"
        )
    
    async def send_response_done(
        self,
        connection_id: str,
        status: str = "completed"
    ):
        """
        发送响应完成信号
        """
        return await self.send_message(
            connection_id,
            {"status": status},
            event="response_done"
        )
    
    async def broadcast(
        self,
        message: dict,
        event: str = "broadcast",
        session_ids: Set[str] = None
    ):
        """
        广播消息到多个连接
        
        Args:
            message: 消息内容
            event: 事件类型
            session_ids: 目标会话ID集合（None表示广播到所有）
        """
        if session_ids is None:
            # 广播到所有连接
            connection_ids = list(self.active_connections.keys())
        else:
            # 广播到指定会话
            connection_ids = [
                self.session_to_connection.get(sid) 
                for sid in session_ids 
                if sid in self.session_to_connection
            ]
        
        # 发送消息
        for conn_id in connection_ids:
            if conn_id:
                await self.send_message(conn_id, message, event)
    
    def get_connection_count(self) -> int:
        """获取活跃连接数"""
        return len(self.active_connections)
    
    def get_session_count(self) -> int:
        """获取会话数"""
        return len(self.session_to_connection)


# 全局实例
websocket_manager = ConnectionManager()
