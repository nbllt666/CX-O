"""
ASR 打断模块 - 伪全双工实现
打断判断由 LLM 完成，使用系统提示词中的打断规则
"""
import logging
from typing import Optional, Callable, Tuple

from server.services.interrupt_llm import InterruptModuleBase

logger = logging.getLogger(__name__)


class ASRInterruptModule(InterruptModuleBase):
    _instance = None
    _independent_timeout: float = 5.0

    def __init__(self):
        super().__init__()
        self.mode = "main_llm"
        self.enabled = True
        self._interrupt_callback: Optional[Callable] = None
        self._is_interrupted = False
        self._tts_playing = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        interrupt_config = config.get("interrupt", {}) or {}
        self.mode = interrupt_config.get("mode", self.mode)
        self.enabled = interrupt_config.get("enabled", self.enabled)
        independent = interrupt_config.get("independent_llm")
        if isinstance(independent, dict) and independent:
            # 采用与 agent_interrupt 一致的字段级合并，复用基类默认值兜底
            self.independent_llm_config = {
                "enabled": independent.get("enabled", False),
                "model": independent.get("model", self.independent_llm_config["model"]),
                "endpoint": independent.get("endpoint", self.independent_llm_config["endpoint"]),
            }

    def set_interrupt_callback(self, callback: Callable):
        self._interrupt_callback = callback

    def set_tts_playing(self, playing: bool):
        self._tts_playing = playing
        if not playing:
            self._is_interrupted = False

    def _build_independent_prompt(self, asr_text: str) -> str:
        return f"""你是一个语音打断判断助手。请根据以下规则判断用户的语音输入：

【用户语音】
{asr_text}

【判断规则】
- CONTINUE：用户还在组织语言，没说完
- IGNORE：用户在自言自语或情绪表达，不需要回复
- INTERRUPT：用户明确提问或需要互动，需要回复

请返回 JSON 格式：
{{"decision": "CONTINUE|IGNORE|INTERRUPT", "reason": "判断原因"}}"""

    async def on_asr_result(self, asr_text: str, is_final: bool = False) -> Tuple[str, bool]:
        if not self.enabled:
            logger.debug("ASR interrupt module is disabled")
            return "IGNORE", False

        if not asr_text or not asr_text.strip():
            logger.debug("Empty ASR text, skipping interrupt check")
            return "IGNORE", False

        if not self._tts_playing:
            logger.debug("TTS not playing, no need to check interrupt")
            return "IGNORE", False

        logger.info(f"Checking interrupt for ASR text: {asr_text}, is_final: {is_final}")

        if self.mode == "main_llm":
            return await self._check_with_main_llm(asr_text)
        else:
            return await self._check_with_independent_llm(asr_text)

    async def _apply_decision(self, decision: str, asr_text: str, llm_response: str = "") -> Tuple[str, bool]:
        """按判定结果执行副作用并返回 (decision, triggered)。

        收敛自 _check_with_main_llm 与 _check_with_independent_llm 相同的
        「INTERRUPT→记录+触发打断 / IGNORE→记录 / CONTINUE→忽略」映射。
        """
        user_message = {"role": "user", "content": asr_text}
        if decision == "INTERRUPT":
            self._context_manager.add_message(self._session_id, user_message)
            logger.info(f"LLM decided to INTERRUPT: {asr_text}")
            await self._trigger_interrupt(asr_text, llm_response)
            return "INTERRUPT", True
        elif decision == "IGNORE":
            self._context_manager.add_message(self._session_id, user_message)
            logger.info(f"LLM decided to IGNORE: {asr_text}")
            return "IGNORE", False
        logger.debug(f"LLM decided to CONTINUE: {asr_text}")
        return "CONTINUE", False

    async def _check_with_main_llm(self, asr_text: str) -> Tuple[str, bool]:
        try:
            response_text = await self._call_main_llm(asr_text)
            if response_text is None:
                logger.warning("主 LLM 未返回响应，无法判定打断")
                return "IGNORE", False

            decision = self._parse_interrupt_decision(response_text)
            return await self._apply_decision(decision, asr_text, response_text)

        except Exception as e:
            logger.error(f"Failed to check interrupt with main LLM: {e}")
            return "IGNORE", False

    def _parse_interrupt_decision(self, response_text: str) -> str:
        if "##[INTERRUPT]##" in response_text:
            return "INTERRUPT"
        elif "##[IGNORE]##" in response_text:
            return "IGNORE"
        elif "##[CONTINUE]##" in response_text:
            return "CONTINUE"
        else:
            logger.warning(f"Unknown interrupt decision in response: {response_text[:100]}")
            return "IGNORE"

    async def _check_with_independent_llm(self, asr_text: str) -> Tuple[str, bool]:
        try:
            result = await self._call_independent_llm(asr_text)
            decision = result.get("decision", "IGNORE")
            return await self._apply_decision(decision, asr_text)

        except Exception as e:
            logger.error(f"Failed to check interrupt with independent LLM: {e}")
            return "IGNORE", False

    async def _trigger_interrupt(self, asr_text: str, llm_response: str = "") -> bool:
        self._is_interrupted = True
        logger.info(f"ASR interrupt triggered: {asr_text}")

        await self._invoke_callback(self._interrupt_callback, asr_text, llm_response)

        return True

    def reset_interrupt(self):
        self._is_interrupted = False

    @property
    def is_interrupted(self) -> bool:
        return self._is_interrupted


def get_asr_interrupt_module() -> ASRInterruptModule:
    return ASRInterruptModule.get_instance()
