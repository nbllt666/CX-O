"""
ASR 打断模块 - 伪全双工实现
打断判断由 LLM 完成，使用系统提示词中的打断规则
"""
import asyncio
import json
import logging
import re
from typing import Optional, Callable, Any, Tuple

logger = logging.getLogger(__name__)


class ASRInterruptModule:
    _instance = None

    def __init__(self):
        self.mode = "main_llm"
        self.enabled = True
        self.independent_llm_config = {
            "enabled": False,
            "model": "qwen2.5:1.5b",
            "endpoint": "http://localhost:11434"
        }
        self._interrupt_callback: Optional[Callable] = None
        self._is_interrupted = False
        self._tts_playing = False
        self._session_id: Optional[str] = None
        self._context_manager: Any = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_config(self, config: dict):
        interrupt_config = config.get("interrupt", {})
        self.mode = interrupt_config.get("mode", "main_llm")
        self.enabled = interrupt_config.get("enabled", True)
        self.independent_llm_config = interrupt_config.get("independent_llm", {
            "enabled": False,
            "model": "qwen2.5:1.5b",
            "endpoint": "http://localhost:11434"
        })

    def set_interrupt_callback(self, callback: Callable):
        self._interrupt_callback = callback

    def set_tts_playing(self, playing: bool):
        self._tts_playing = playing
        if not playing:
            self._is_interrupted = False

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

    async def _check_with_main_llm(self, asr_text: str) -> Tuple[str, bool]:
        try:
            from server.dependencies import get_llm_client
            llm = get_llm_client()
        except Exception as e:
            logger.warning(f"LLM client not available, cannot check interrupt: {e}")
            return "IGNORE", False

        try:
            messages = self._get_context_with_system_prompt()
            user_message = {"role": "user", "content": asr_text}
            messages.append(user_message)

            response = await llm.chat(messages=messages, stream=False)

            if not response or response.error:
                logger.warning(f"No response from main LLM: {response.error if response else 'None'}")
                return "IGNORE", False

            response_text = response.content or ""

            decision = self._parse_interrupt_decision(response_text)

            if decision == "INTERRUPT":
                self._context_manager.add_message(self._session_id, user_message)
                logger.info(f"Main LLM decided to INTERRUPT: {asr_text}")
                await self._trigger_interrupt(asr_text, response_text)
                return "INTERRUPT", True
            elif decision == "IGNORE":
                self._context_manager.add_message(self._session_id, user_message)
                logger.info(f"Main LLM decided to IGNORE: {asr_text}")
                return "IGNORE", False
            else:
                logger.debug(f"Main LLM decided to CONTINUE: {asr_text}")
                return "CONTINUE", False

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

            if decision == "INTERRUPT":
                self._context_manager.add_message(self._session_id, {"role": "user", "content": asr_text})
                logger.info(f"Independent LLM decided to INTERRUPT: {asr_text}")
                await self._trigger_interrupt(asr_text)
                return "INTERRUPT", True
            elif decision == "IGNORE":
                self._context_manager.add_message(self._session_id, {"role": "user", "content": asr_text})
                logger.info(f"Independent LLM decided to IGNORE: {asr_text}")
                return "IGNORE", False
            else:
                logger.debug(f"Independent LLM decided to CONTINUE: {asr_text}")
                return "CONTINUE", False

        except Exception as e:
            logger.error(f"Failed to check interrupt with independent LLM: {e}")
            return "IGNORE", False

    async def _call_independent_llm(self, asr_text: str) -> dict:
        import aiohttp

        prompt = f"""你是一个语音打断判断助手。请根据以下规则判断用户的语音输入：

【用户语音】
{asr_text}

【判断规则】
- CONTINUE：用户还在组织语言，没说完
- IGNORE：用户在自言自语或情绪表达，不需要回复
- INTERRUPT：用户明确提问或需要互动，需要回复

请返回 JSON 格式：
{{"decision": "CONTINUE|IGNORE|INTERRUPT", "reason": "判断原因"}}"""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.independent_llm_config['endpoint']}/api/generate",
                    json={
                        "model": self.independent_llm_config["model"],
                        "prompt": prompt,
                        "stream": False,
                        "format": "json"
                    },
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    result = await response.json()
                    text = result.get("response", "")

                    try:
                        parsed = json.loads(text)
                        return {
                            "decision": parsed.get("decision", "IGNORE"),
                            "reason": parsed.get("reason", "")
                        }
                    except json.JSONDecodeError:
                        if "INTERRUPT" in text:
                            return {"decision": "INTERRUPT", "reason": "从文本解析"}
                        elif "IGNORE" in text:
                            return {"decision": "IGNORE", "reason": "从文本解析"}
                        return {"decision": "CONTINUE", "reason": "JSON解析失败"}

        except asyncio.TimeoutError:
            logger.warning("Independent LLM timeout")
            return {"decision": "CONTINUE", "reason": "超时"}
        except Exception as e:
            logger.error(f"Independent LLM error: {e}")
            return {"decision": "IGNORE", "reason": str(e)}

    async def _trigger_interrupt(self, asr_text: str, llm_response: str = "") -> bool:
        self._is_interrupted = True
        logger.info(f"ASR interrupt triggered: {asr_text}")

        if self._interrupt_callback:
            try:
                if asyncio.iscoroutinefunction(self._interrupt_callback):
                    await self._interrupt_callback(asr_text, llm_response)
                else:
                    self._interrupt_callback(asr_text, llm_response)
            except Exception as e:
                logger.error(f"Interrupt callback error: {e}")

        return True

    def reset_interrupt(self):
        self._is_interrupted = False

    @property
    def is_interrupted(self) -> bool:
        return self._is_interrupted


def get_asr_interrupt_module() -> ASRInterruptModule:
    return ASRInterruptModule.get_instance()
