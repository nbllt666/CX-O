"""
Agent 打断用户模块 - 双向全双工
Agent 可以在用户说话过程中判断是否可以插话
"""
import inspect
import json
import logging
import time
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class UserSpeechState:
    is_speaking: bool = False
    current_text: str = ""
    start_time: float = 0
    last_update_time: float = 0
    text_segments: list = field(default_factory=list)


class AgentInterruptUser:
    _instance = None

    def __init__(self):
        self.enabled = True
        self.mode = "main_llm"  # main_llm / independent_llm
        self.interrupt_threshold_ms = 500
        self.min_speech_duration_ms = 1000
        self._user_state = UserSpeechState()
        self._interrupt_user_callback: Optional[Callable] = None
        self._start_tts_callback: Optional[Callable] = None
        self._asr_client: Any = None
        self._last_interrupt_time: float = 0
        self._interrupt_cooldown_ms = 3000
        self._session_id: Optional[str] = None
        self._context_manager: Any = None
        # 独立小模型判定：只输出 INTERRUPT/IGNORE/CONTINUE 标记，不生成回复内容
        # （回复内容由主 pipeline 生成），避免占用主 LLM 并发槽
        self.independent_llm_config = {
            "enabled": False,
            "model": "qwen2.5:1.5b",
            "endpoint": "http://localhost:11434",
        }

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        agent_interrupt = config.get("agent_interrupt", {})
        self.enabled = agent_interrupt.get("enabled", True)
        self.mode = agent_interrupt.get("mode", "main_llm")
        self.interrupt_threshold_ms = agent_interrupt.get("interrupt_threshold_ms", 500)
        self.min_speech_duration_ms = agent_interrupt.get("min_speech_duration_ms", 1000)
        self._interrupt_cooldown_ms = agent_interrupt.get("interrupt_cooldown_ms", 3000)
        independent = agent_interrupt.get("independent_llm", {})
        if isinstance(independent, dict) and independent:
            self.independent_llm_config = {
                "enabled": independent.get("enabled", False),
                "model": independent.get("model", self.independent_llm_config["model"]),
                "endpoint": independent.get("endpoint", self.independent_llm_config["endpoint"]),
            }

    def set_asr_client(self, client: Any):
        self._asr_client = client

    def set_session_id(self, session_id: str):
        self._session_id = session_id

    def set_context_manager(self, context_manager: Any):
        self._context_manager = context_manager

    def _get_context(self) -> list:
        if self._context_manager and self._session_id:
            return self._context_manager.get_context(self._session_id)
        return []

    def _get_context_with_system_prompt(self) -> list:
        if self._context_manager and self._session_id:
            return self._context_manager.get_context_with_system_prompt(self._session_id)
        return []

    def set_callbacks(
        self,
        interrupt_user_callback: Optional[Callable] = None,
        start_tts_callback: Optional[Callable] = None
    ):
        self._interrupt_user_callback = interrupt_user_callback
        self._start_tts_callback = start_tts_callback

    def on_user_speech_start(self):
        self._user_state = UserSpeechState(
            is_speaking=True,
            start_time=time.time(),
            last_update_time=time.time()
        )
        logger.debug("User speech started")

    def on_user_speech_end(self):
        if self._user_state.is_speaking:
            logger.debug(f"User speech ended: {self._user_state.current_text}")
            self._user_state.is_speaking = False

    async def on_asr_partial_result(self, text: str, is_final: bool = False) -> dict:
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
            return {
                "should_interrupt": True,
                "should_reply": result.get("should_reply", True),
                "reply_content": result.get("reply_content", "")
            }

        if is_final:
            return {
                "should_interrupt": False,
                "should_reply": result.get("should_reply", False),
                "reply_content": result.get("reply_content", "")
            }

        return {"should_interrupt": False, "should_reply": False}

    async def _check_can_interrupt(self, asr_text: str, is_final: bool) -> dict:
        # 独立小模型模式：只输出标记，不占用主 LLM 并发槽
        if self.mode == "independent_llm":
            return await self._check_with_independent_llm(asr_text, is_final)

        try:
            from server.dependencies import get_llm_client
            llm = get_llm_client()
        except Exception as e:
            logger.warning(f"LLM client not available for agent interrupt: {e}")
            return {"can_interrupt": False, "should_reply": False}

        try:
            messages = self._get_context_with_system_prompt()
            # 注入结构化判定指令：主 LLM 也输出三态标记（CONTINUE/IGNORE/INTERRUPT），
            # 打断时直接输出插话内容，不打断时只输出标记（符合"按模式区分"设计）
            judgment_prompt = self._build_interrupt_prompt(asr_text, is_final)
            user_message = {"role": "user", "content": judgment_prompt}
            messages.append(user_message)

            response = await llm.chat(messages=messages, stream=False)

            if not response or response.error:
                return {"can_interrupt": False, "should_reply": False}

            response_text = response.content or ""

            return self._parse_interrupt_response(response_text, is_final)

        except Exception as e:
            logger.error(f"Failed to check can interrupt: {e}")
            return {"can_interrupt": False, "should_reply": False}

    async def _check_with_independent_llm(self, asr_text: str, is_final: bool) -> dict:
        """独立小模型判定：只输出 INTERRUPT/IGNORE/CONTINUE 标记，不生成回复内容。

        回复内容由主 pipeline 生成（独立模式命中打断后仅停 TTS 让位，不再额外播 reply）。
        """
        if not self.independent_llm_config.get("enabled"):
            logger.info("independent_llm 未启用，跳过插话判定")
            return {"can_interrupt": False, "should_reply": False, "reply_content": ""}

        result = await self._call_independent_llm(asr_text)
        decision = result.get("decision", "IGNORE")

        if decision == "INTERRUPT":
            return {"can_interrupt": True, "should_reply": True, "reply_content": ""}
        if decision == "CONTINUE":
            # 用户还在组织语言：不打断，继续等待
            return {"can_interrupt": False, "should_reply": False, "reply_content": ""}
        return {"can_interrupt": False, "should_reply": False, "reply_content": ""}

    async def _call_independent_llm(self, asr_text: str) -> dict:
        """调用独立小模型判断能否插话，返回 JSON decision。

        复用共享助手 call_ollama_decision 统一 HTTP 调用、JSON 解析与兜底降级。
        """
        from server.services.interrupt_llm import call_ollama_decision

        prompt = f"""你是一个语音插话判断助手。请根据规则判断用户的语音输入：

【用户语音】
{asr_text}

【判断规则】
- CONTINUE：用户还在组织语言，没说完，不要打断
- IGNORE：用户在自言自语或情绪表达，不需要 Agent 插话
- INTERRUPT：用户明确提问或需要 Agent 立即互动，可以插话

请严格返回 JSON 格式：
{{"decision": "CONTINUE|IGNORE|INTERRUPT", "reason": "判断原因"}}"""

        return await call_ollama_decision(
            endpoint=self.independent_llm_config["endpoint"],
            model=self.independent_llm_config["model"],
            prompt=prompt,
            timeout=3.0,
        )

    def _build_interrupt_prompt(self, asr_text: str, is_final: bool, context: list = None) -> str:
        status = "用户说完了" if is_final else "用户正在说话"

        return f"""你是一个语音交互助手。{status}，你需要判断是否需要插话回复。

【用户说的话】
{asr_text}

【判断规则】
- CONTINUE：用户还在组织语言，没说完，继续等待，不要打断
- IGNORE：用户在自言自语或情绪表达，不需要 Agent 插话
- INTERRUPT：用户明确提问或需要 Agent 立即互动，可以立即插话

【输出格式】严格返回 JSON：
{{"decision": "CONTINUE|IGNORE|INTERRUPT", "reply_content": "当 decision 为 INTERRUPT 时，这是你要插话说出的内容（简短口语）；否则为空字符串", "reason": "判断原因"}}"""

    def _parse_interrupt_response(self, response_text: str, is_final: bool) -> dict:
        try:
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response_text[json_start:json_end]
                result = json.loads(json_str)

                decision = result.get("decision", "CONTINUE")
                reply_content = result.get("reply_content", "")

                # 三态标记映射：INTERRUPT → 打断并播内容；CONTINUE/IGNORE → 不打断
                if decision == "INTERRUPT":
                    return {
                        "can_interrupt": True,
                        "should_reply": True,
                        "reply_content": reply_content,
                        "reason": result.get("reason", ""),
                    }
                return {
                    "can_interrupt": False,
                    "should_reply": False,
                    "reply_content": "",
                    "reason": result.get("reason", ""),
                }
        except json.JSONDecodeError:
            pass

        question_indicators = ["？", "?", "吗", "呢", "什么", "怎么", "为什么", "哪里", "谁"]
        has_question = any(indicator in response_text for indicator in question_indicators)

        return {
            "can_interrupt": has_question,
            "should_reply": has_question,
            "reply_content": "",
            "reason": "从文本推断"
        }

    async def interrupt_user(self, reply_content: str = "") -> bool:
        logger.info(f"Agent interrupting user with reply: {reply_content[:50]}...")

        if self._interrupt_user_callback:
            try:
                if inspect.iscoroutinefunction(self._interrupt_user_callback):
                    await self._interrupt_user_callback()
                else:
                    self._interrupt_user_callback()
            except Exception as e:
                logger.error(f"Interrupt user callback error: {e}")

        self._user_state.is_speaking = False

        if self._start_tts_callback and reply_content:
            try:
                if inspect.iscoroutinefunction(self._start_tts_callback):
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
    return AgentInterruptUser.get_instance()
