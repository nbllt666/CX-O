"""
打断管理器 - 管理 TTS 中断
"""
import asyncio
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class InterruptManager:
    """
    打断管理器 - 管理 TTS 中断和打断后的新回复流程
    """
    _instance = None
    
    def __init__(self):
        self._tts_stop_callback: Optional[Callable] = None
        self._is_tts_playing = False
        self._current_session_id: Optional[str] = None
        self._cxhms_client = None
        self._reply_callback: Optional[Callable] = None
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def set_cxhms_client(self, client):
        """设置 CXHMS 客户端"""
        self._cxhms_client = client
    
    def set_reply_callback(self, callback: Callable):
        """设置回复回调，用于处理 CXHMS 回复"""
        self._reply_callback = callback
    
    def set_tts_stop_callback(self, callback: Callable):
        """设置 TTS 停止回调"""
        self._tts_stop_callback = callback
    
    def set_tts_playing(self, playing: bool, session_id: Optional[str] = None):
        """设置 TTS 播放状态"""
        self._is_tts_playing = playing
        self._current_session_id = session_id
        logger.info(f"TTS playing state changed: {playing}, session: {session_id}")
    
    def is_tts_playing(self) -> bool:
        """检查 TTS 是否正在播放"""
        return self._is_tts_playing
    
    async def interrupt_tts(self, reason: str = ""):
        """
        中断当前 TTS 播报
        """
        if not self._is_tts_playing:
            logger.info("No TTS playing, skip interrupt")
            return False
        
        logger.info(f"Interrupting TTS: {reason}")
        
        if self._tts_stop_callback:
            if asyncio.iscoroutinefunction(self._tts_stop_callback):
                await self._tts_stop_callback()
            else:
                self._tts_stop_callback()
        
        self._is_tts_playing = False
        return True
    
    async def on_new_reply_triggered(self, session_id: str, context_messages: list):
        """
        当打断触发新回复时调用
        触发 CXHMS 生成新回复
        """
        logger.info(f"New reply triggered for session: {session_id}")
        
        if not self._cxhms_client:
            logger.warning("CXHMS client not available for reply generation")
            return False
        
        try:
            self._is_tts_playing = True
            
            async def handle_stream_response(response: dict):
                if response.get("type") == "error":
                    logger.error(f"CXHMS reply error: {response.get('message')}")
                    if self._reply_callback:
                        self._reply_callback(response)
                    return
                
                content = response.get("content", response.get("text", ""))
                if content:
                    logger.info(f"CXHMS reply chunk: {content[:100]}...")
                    if self._reply_callback:
                        self._reply_callback(response)
                
                if response.get("is_final", False):
                    logger.info("CXHMS reply stream completed")
            
            await self._cxhms_client.stream("chat", {
                "messages": context_messages,
                "stream": True
            }, handle_stream_response, timeout=60.0)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to trigger CXHMS reply: {e}")
            self._is_tts_playing = False
            return False


def get_interrupt_manager() -> InterruptManager:
    return InterruptManager.get_instance()
