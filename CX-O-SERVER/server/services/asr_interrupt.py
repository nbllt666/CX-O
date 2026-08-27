"""
ASR 打断模块 - 伪全双工实现
打断判断由 LLM 完成，使用系统提示词中的打断规则
"""
import logging
from typing import Optional, Callable, Tuple

from server.services.interrupt_llm import InterruptModuleBase

logger = logging.getLogger(__name__)


class ASRInterruptModule(InterruptModuleBase):
    """ASR 打断模块（伪全双工实现），由 LLM 依据系统提示词规则判断是否打断当前 TTS 播报。"""

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
            return await self._check_with_main_llm(asr_text, is_final)
        else:
            return await self._check_with_independent_llm(asr_text, is_final)

    async def _apply_decision(self, decision: str, asr_text: str, llm_response: str = "",
                              is_final: bool = False) -> Tuple[str, bool]:
        """按判定结果执行副作用并返回 (decision, triggered)。

        收敛自 _check_with_main_llm 与 _check_with_independent_llm 相同的
        「INTERRUPT→记录+触发打断 / IGNORE→记录 / CONTINUE→忽略」映射。

        上下文去重：live 路径同一 utterance 会以多帧 partial 演进调用本模块；
        打断判定（_trigger_interrupt）保持对 partial 的即时响应以维持实时性，
        但「写回真实上下文」（add_message）仅在 is_final 时执行一次，避免
        同一句子的多个 partial 被重复写入真实 context 造成膨胀/污染。
        """
        user_message = {"role": "user", "content": asr_text}
        if decision == "INTERRUPT":
            if is_final:
                self._context_manager.add_message(self._session_id, user_message)
            logger.info(f"LLM decided to INTERRUPT: {asr_text}")
            await self._trigger_interrupt(asr_text, llm_response)
            return "INTERRUPT", True
        elif decision == "IGNORE":
            if is_final:
                self._context_manager.add_message(self._session_id, user_message)
            logger.info(f"LLM decided to IGNORE: {asr_text}")
            return "IGNORE", False
        logger.debug(f"LLM decided to CONTINUE: {asr_text}")
        return "CONTINUE", False

    async def _check_with_main_llm(self, asr_text: str, is_final: bool = False) -> Tuple[str, bool]:
        try:
            response_text = await self._call_main_llm(asr_text)
            if response_text is None:
                logger.warning("主 LLM 未返回响应，无法判定打断")
                return "IGNORE", False

            decision = self._parse_interrupt_decision(response_text)
            return await self._apply_decision(decision, asr_text, response_text, is_final)

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

    async def _check_with_independent_llm(self, asr_text: str, is_final: bool = False) -> Tuple[str, bool]:
        try:
            result = await self._call_independent_llm(asr_text)
            decision = result.get("decision", "IGNORE")
            return await self._apply_decision(decision, asr_text, is_final=is_final)

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


def get_asr_interrupt_module(client_id: Optional[str] = None) -> ASRInterruptModule:
    """获取 ASR 打断模块。

    未指定 client_id：返回全局默认单例（向后兼容）。
    指定 client_id：返回该客户端的独立实例，使各会话的 _tts_playing /
    _is_interrupted 等状态互不串扰（A 播 TTS 不影响 B 的打断判定）。
    """
    if client_id is None:
        return ASRInterruptModule.get_instance()
    if client_id not in _asr_interrupt_instances:
        instance = ASRInterruptModule()
        _inherit_asr_config(ASRInterruptModule.get_instance(), instance)
        _asr_interrupt_instances[client_id] = instance
    return _asr_interrupt_instances[client_id]


def release_asr_interrupt_module(client_id: str) -> None:
    """释放指定客户端的 ASR 打断模块实例（不影响其它客户端与默认单例）。"""
    _asr_interrupt_instances.pop(client_id, None)


def _inherit_asr_config(src: ASRInterruptModule, dst: ASRInterruptModule) -> None:
    """从默认单例复制配置到新创建的 per-client 实例，保持全局配置一致。"""
    dst.mode = src.mode
    dst.enabled = src.enabled
    dst.independent_llm_config = dict(src.independent_llm_config)


# per-client 打断模块注册表（client_id -> 独立实例）
_asr_interrupt_instances: dict = {}
