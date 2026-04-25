"""
ASR 打断模块 - 伪全双工实现
用户打断 TTS 时直接触发打断，将用户内容加入上下文并标记 speaking 状态
"""
import asyncio
import logging
from typing import Optional, Callable, Any, Tuple

logger = logging.getLogger(__name__)


class ASRInterruptModule:
    """
    ASR 打断模块 - 伪全双工
    
    用户打断 TTS 时：
    1. 直接触发打断，不需要 LLM 判断
    2. 将用户说的内容加入上下文，标记 speaking 状态
    3. LLM 在生成回复时知道这是打断场景
    
    注意：此类不再使用单例模式，每个客户端应有独立实例
    """
    
    def __init__(self):
        self.enabled = True
        self._interrupt_callback: Optional[Callable] = None
        self._is_interrupted = False
        self._tts_playing = False
        self._session_id: Optional[str] = None
        self._context_manager: Any = None
    
    def set_config(self, config: dict):
        """设置配置"""
        interrupt_config = config.get("interrupt", {})
        self.enabled = interrupt_config.get("enabled", True)
    
    def set_interrupt_callback(self, callback: Callable):
        """设置打断回调"""
        self._interrupt_callback = callback
    
    def set_tts_playing(self, playing: bool):
        """设置 TTS 是否正在播放"""
        self._tts_playing = playing
        if not playing:
            self._is_interrupted = False
    
    def set_session_id(self, session_id: str):
        """设置当前会话 ID"""
        self._session_id = session_id
    
    def set_context_manager(self, context_manager: Any):
        """设置上下文管理器"""
        self._context_manager = context_manager
    
    def set_cxhms_client(self, client: Any):
        """设置 CXHMS 客户端（兼容旧接口）"""
        pass
    
    async def on_asr_result(self, asr_text: str, is_final: bool = False) -> Tuple[str, bool]:
        """
        当收到 ASR 识别结果时调用

        Args:
            asr_text: ASR 识别的累积内容
            is_final: 是否是最终识别结果

        Returns:
            Tuple[str, bool]: (决策标记, 是否触发打断)
        """
        if not self.enabled:
            return "CONTINUE", False

        if not asr_text or not asr_text.strip():
            return "CONTINUE", False

        if not self._tts_playing:
            return "CONTINUE", False

        logger.info(f"User interrupted TTS with: {asr_text}, is_final: {is_final}")

        user_message = {
            "role": "user",
            "content": asr_text,
            "metadata": {
                "speaking": True,
                "interrupt": True,
                "is_final": is_final
            }
        }

        if self._context_manager and self._session_id:
            self._context_manager.add_message(self._session_id, user_message)

        if is_final:
            logger.info(f"User finished speaking, triggering interrupt: {asr_text}")
            await self._trigger_interrupt(asr_text)
            return "INTERRUPT", True

        return "CONTINUE", False
    
    async def _trigger_interrupt(self, asr_text: str) -> bool:
        """触发打断"""
        self._is_interrupted = True
        logger.info(f"TTS interrupted by user: {asr_text}")
        
        if self._interrupt_callback:
            try:
                if asyncio.iscoroutinefunction(self._interrupt_callback):
                    await self._interrupt_callback(asr_text, "")
                else:
                    self._interrupt_callback(asr_text, "")
            except Exception as e:
                logger.error(f"Interrupt callback error: {e}")
        
        return True
    
    def reset_interrupt(self):
        """重置打断状态"""
        self._is_interrupted = False
    
    @property
    def is_interrupted(self) -> bool:
        return self._is_interrupted


def get_asr_interrupt_module() -> ASRInterruptModule:
    return ASRInterruptModule()


create_asr_interrupt_module = get_asr_interrupt_module
