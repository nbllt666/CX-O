"""
Agent 打断用户模块 - 双向全双工
Agent 可以在用户说话过程中判断是否可以插话
"""
import asyncio
import logging
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UserSpeechState:
    """用户说话状态"""
    is_speaking: bool = False
    current_text: str = ""
    start_time: float = 0
    last_update_time: float = 0
    text_segments: list = field(default_factory=list)


class AgentInterruptUser:
    """
    Agent 打断用户模块
    
    功能：
    1. 实时监听用户说话
    2. LLM 判断是否可以插话
    3. 打断用户并开始回复
    
    注意：此类不再使用单例模式，每个客户端应有独立实例
    """
    
    def __init__(self):
        self.enabled = True
        self.interrupt_threshold_ms = 500
        self.min_speech_duration_ms = 1000
        self._user_state = UserSpeechState()
        self._cxhms_client: Any = None
        self._interrupt_user_callback: Optional[Callable] = None
        self._start_tts_callback: Optional[Callable] = None
        self._asr_client: Any = None
        self._last_interrupt_time: float = 0
        self._interrupt_cooldown_ms = 3000
        self._session_id: Optional[str] = None
        self._context_manager: Any = None
    
    def set_config(self, config: dict):
        """设置配置"""
        agent_interrupt = config.get("agent_interrupt", {})
        self.enabled = agent_interrupt.get("enabled", True)
        self.interrupt_threshold_ms = agent_interrupt.get("interrupt_threshold_ms", 500)
        self.min_speech_duration_ms = agent_interrupt.get("min_speech_duration_ms", 1000)
        self._interrupt_cooldown_ms = agent_interrupt.get("interrupt_cooldown_ms", 3000)
    
    def set_cxhms_client(self, client: Any):
        """设置 CXHMS 客户端"""
        self._cxhms_client = client
    
    def set_asr_client(self, client: Any):
        """设置 ASR 客户端"""
        self._asr_client = client
    
    def set_session_id(self, session_id: str):
        """设置当前会话 ID"""
        self._session_id = session_id
    
    def set_context_manager(self, context_manager: Any):
        """设置上下文管理器"""
        self._context_manager = context_manager
    
    def _get_context(self) -> list:
        """获取当前会话的上下文（不含系统提示词）"""
        if self._context_manager and self._session_id:
            return self._context_manager.get_context(self._session_id)
        return []
    
    def _get_context_with_system_prompt(self) -> list:
        """获取当前会话的完整上下文（包含系统提示词）"""
        if self._context_manager and self._session_id:
            return self._context_manager.get_context_with_system_prompt(self._session_id)
        return []
    
    def set_callbacks(
        self,
        interrupt_user_callback: Optional[Callable] = None,
        start_tts_callback: Optional[Callable] = None
    ):
        """设置回调函数"""
        self._interrupt_user_callback = interrupt_user_callback
        self._start_tts_callback = start_tts_callback
    
    def on_user_speech_start(self):
        """用户开始说话"""
        self._user_state = UserSpeechState(
            is_speaking=True,
            start_time=time.time(),
            last_update_time=time.time()
        )
        logger.debug("User speech started")
    
    def on_user_speech_end(self):
        """用户结束说话"""
        if self._user_state.is_speaking:
            logger.debug(f"User speech ended: {self._user_state.current_text}")
            self._user_state.is_speaking = False
    
    async def on_asr_partial_result(self, text: str, is_final: bool = False) -> dict:
        """
        处理 ASR 部分识别结果

        两种场景：
        1. Agent 打断用户（插话）：用户说话中，Agent 判断需要插话
        2. 用户说完 Agent 回复：用户说完了，Agent 正常回复

        Args:
            text: 识别到的文本
            is_final: ASR 是否判断用户说完了

        Returns:
            dict: {
                "should_interrupt": bool,  # Agent 是否要打断用户（插话）
                "should_reply": bool,      # 用户说完后 Agent 是否要回复
                "reply_content": str
            }
        """
        if not self.enabled:
            return {"should_interrupt": False, "should_reply": False}

        current_time = time.time()
        self._user_state.current_text = text
        self._user_state.last_update_time = current_time

        if text:
            self._user_state.text_segments.append({
                "text": text,
                "time": current_time,
                "is_final": is_final
            })

        speech_duration_ms = (current_time - self._user_state.start_time) * 1000

        if speech_duration_ms < self.min_speech_duration_ms:
            return {"should_interrupt": False, "should_reply": False}

        if current_time - self._last_interrupt_time < self._interrupt_cooldown_ms / 1000:
            return {"should_interrupt": False, "should_reply": False}

        result = await self._check_can_interrupt(text, is_final)

        if result.get("can_interrupt"):
            self._last_interrupt_time = current_time
            logger.info(f"Agent interrupting user (barge-in): {text}")
            return {
                "should_interrupt": True,
                "should_reply": False,
                "reply_content": result.get("reply_content", "")
            }

        if is_final and result.get("should_reply"):
            logger.info(f"User finished speaking, agent replying: {text}")
            return {
                "should_interrupt": False,
                "should_reply": True,
                "reply_content": result.get("reply_content", "")
            }

        return {"should_interrupt": False, "should_reply": False}
    
    async def _check_can_interrupt(self, asr_text: str, is_final: bool) -> dict:
        """
        检查 Agent 是否需要打断用户或回复

        LLM 输出格式：
        - INTERRUPT:内容 - Agent 打断用户
        - REPLY:内容 - 用户说完后回复
        - WAIT - 不需要操作

        注意：WAIT 不加入上下文，节省 token

        Returns:
            dict: {
                "can_interrupt": bool,
                "should_reply": bool,
                "reply_content": str
            }
        """
        if not self._cxhms_client:
            logger.warning("CXHMS client not set for agent interrupt")
            return {"can_interrupt": False, "should_reply": False}

        try:
            messages = self._get_context_with_system_prompt()
            user_message = {
                "role": "user",
                "content": asr_text,
                "metadata": {
                    "speaking": True,
                    "asr_is_final": is_final
                }
            }
            messages.append(user_message)

            response = await self._cxhms_client.request("chat", {
                "messages": messages,
                "stream": False
            })

            if not response:
                return {"can_interrupt": False, "should_reply": False}

            response_text = response.get("content", "") or response.get("text", "")

            result = self._parse_interrupt_response(response_text, is_final)

            if result.get("can_interrupt") or result.get("should_reply"):
                if self._context_manager and self._session_id:
                    self._context_manager.add_message(self._session_id, user_message)

            return result

        except Exception as e:
            logger.error(f"Failed to check can interrupt: {e}")
            return {"can_interrupt": False, "should_reply": False}
    
    def _build_interrupt_prompt(self, asr_text: str, is_final: bool, context: list = None) -> str:
        """构建打断判断 Prompt"""
        status = "用户说完了" if is_final else "用户正在说话"

        return f"""你是一个直播助手。{status}。

【用户说的话】
{asr_text}

【输出规则】
- 需要打断用户（纠正错误/补充信息）：输出 INTERRUPT:你的内容
- 需要回复用户：输出 REPLY:你的内容
- 不需要操作：输出 WAIT"""
    
    def _parse_interrupt_response(self, response_text: str, is_final: bool) -> dict:
        """
        解析 LLM 响应

        格式：
        - INTERRUPT:内容 - Agent 打断用户
        - REPLY:内容 - 用户说完后回复
        - WAIT - 不需要操作
        """
        if not response_text:
            return {"can_interrupt": False, "should_reply": False}

        text = response_text.strip()

        if text.upper().startswith("INTERRUPT:"):
            content = text[len("INTERRUPT:"):].strip()
            return {
                "can_interrupt": True,
                "should_reply": False,
                "reply_content": content
            }

        if text.upper().startswith("REPLY:"):
            content = text[len("REPLY:"):].strip()
            return {
                "can_interrupt": False,
                "should_reply": True,
                "reply_content": content
            }

        if text.upper() == "WAIT":
            return {"can_interrupt": False, "should_reply": False}

        if is_final and text:
            return {
                "can_interrupt": False,
                "should_reply": True,
                "reply_content": text
            }

        return {"can_interrupt": False, "should_reply": False}
    
    async def interrupt_user(self, reply_content: str = "") -> bool:
        """
        打断用户说话
        
        Args:
            reply_content: 要回复的内容
            
        Returns:
            bool: 是否成功打断
        """
        logger.info(f"Agent interrupting user with reply: {reply_content[:50]}...")
        
        if self._interrupt_user_callback:
            try:
                if asyncio.iscoroutinefunction(self._interrupt_user_callback):
                    await self._interrupt_user_callback()
                else:
                    self._interrupt_user_callback()
            except Exception as e:
                logger.error(f"Interrupt user callback error: {e}")
        
        self._user_state.is_speaking = False
        
        if self._start_tts_callback and reply_content:
            try:
                if asyncio.iscoroutinefunction(self._start_tts_callback):
                    await self._start_tts_callback(reply_content)
                else:
                    self._start_tts_callback(reply_content)
            except Exception as e:
                logger.error(f"Start TTS callback error: {e}")
        
        return True
    
    @property
    def is_user_speaking(self) -> bool:
        return self._user_state.is_speaking
    
    @property
    def user_current_text(self) -> str:
        return self._user_state.current_text


def get_agent_interrupt_module() -> AgentInterruptUser:
    return AgentInterruptUser()


create_agent_interrupt_module = get_agent_interrupt_module
