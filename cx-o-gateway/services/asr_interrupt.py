"""
ASR 打断模块 - 伪全双工实现
打断判断由 LLM 完成，不使用简单关键词匹配
"""
import asyncio
import json
import logging
import re
from typing import Optional, Callable, Any

logger = logging.getLogger(__name__)


class ASRInterruptModule:
    """
    ASR 打断模块 - 伪全双工
    
    支持两种模式：
    1. 主 LLM 模式 - 调用 CXHMS 生成回复，解析 ##[interrupt]## 或 ##[no_reply]##
    2. 独立 LLM 模式 - 调用独立小 LLM (Qwen2.5-1.5B)，返回 interrupt: true/false
    """
    _instance = None
    
    def __init__(self):
        self.mode = "main_llm"
        self.enabled = True
        self.main_llm_config = {
            "enabled": True,
            "prompt": ""
        }
        self.independent_llm_config = {
            "enabled": False,
            "model": "qwen2.5:1.5b",
            "endpoint": "http://localhost:11434"
        }
        self._interrupt_callback: Optional[Callable] = None
        self._is_interrupted = False
        self._tts_playing = False
        self._cxhms_client: Any = None
        
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def set_config(self, config: dict):
        """设置配置"""
        interrupt_config = config.get("interrupt", {})
        self.mode = interrupt_config.get("mode", "main_llm")
        self.enabled = interrupt_config.get("enabled", True)
        self.main_llm_config = interrupt_config.get("main_llm", {
            "enabled": True,
            "prompt": ""
        })
        self.independent_llm_config = interrupt_config.get("independent_llm", {
            "enabled": False,
            "model": "qwen2.5:1.5b",
            "endpoint": "http://localhost:11434"
        })
    
    def set_interrupt_callback(self, callback: Callable):
        """设置打断回调"""
        self._interrupt_callback = callback
    
    def set_tts_playing(self, playing: bool):
        """设置 TTS 是否正在播放"""
        self._tts_playing = playing
        if not playing:
            self._is_interrupted = False
    
    def set_cxhms_client(self, client: Any):
        """设置 CXHMS 客户端"""
        self._cxhms_client = client
    
    async def on_asr_result(self, asr_text: str) -> bool:
        """
        当收到 ASR 识别结果时调用
        
        Returns:
            bool: 是否触发了打断
        """
        if not self.enabled:
            logger.debug("ASR interrupt module is disabled")
            return False
        
        if not asr_text or not asr_text.strip():
            logger.debug("Empty ASR text, skipping interrupt check")
            return False
        
        if not self._tts_playing:
            logger.debug("TTS not playing, no need to check interrupt")
            return False
        
        logger.info(f"Checking interrupt for ASR text: {asr_text}")
        
        if self.mode == "main_llm":
            return await self._check_with_main_llm(asr_text)
        else:
            return await self._check_with_independent_llm(asr_text)
    
    async def _check_with_main_llm(self, asr_text: str) -> bool:
        """
        使用主 LLM 判断是否需要打断
        
        主 LLM 会输出：
        - ##[interrupt]## 表示需要打断并回复
        - ##[no_reply]## 表示不需要回复
        """
        if not self._cxhms_client:
            logger.warning("CXHMS client not set, cannot check interrupt with main LLM")
            return False
        
        try:
            prompt = self._build_main_llm_prompt(asr_text)
            
            response = await self._cxhms_client.send_message(
                message=prompt,
                context=[],
                stream=False
            )
            
            if not response:
                logger.warning("No response from main LLM")
                return False
            
            response_text = response.get("content", "") or response.get("text", "")
            
            if "##[interrupt]##" in response_text:
                logger.info(f"Main LLM decided to interrupt: {asr_text}")
                return await self._trigger_interrupt(asr_text, response_text)
            elif "##[no_reply]##" in response_text:
                logger.info(f"Main LLM decided no reply needed: {asr_text}")
                return False
            else:
                logger.debug(f"Main LLM response has no interrupt marker: {response_text[:100]}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to check interrupt with main LLM: {e}")
            return False
    
    async def _check_with_independent_llm(self, asr_text: str) -> bool:
        """
        使用独立 LLM 判断是否需要打断
        
        独立 LLM 返回 JSON: {"interrupt": true/false, "reason": "..."}
        """
        try:
            result = await self._call_independent_llm(asr_text)
            
            if result.get("interrupt"):
                logger.info(f"Independent LLM decided to interrupt: {asr_text}, reason: {result.get('reason')}")
                return await self._trigger_interrupt(asr_text)
            else:
                logger.debug(f"Independent LLM decided no interrupt: {asr_text}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to check interrupt with independent LLM: {e}")
            return False
    
    def _build_main_llm_prompt(self, asr_text: str) -> str:
        """构建主 LLM 打断判断 Prompt"""
        custom_prompt = self.main_llm_config.get("prompt", "")
        
        if custom_prompt:
            return custom_prompt.replace("{asr_text}", asr_text)
        
        return f"""你是一个直播助手。当前正在通过 TTS 播报回复。

用户刚才说的话: {asr_text}

请判断是否需要打断当前回复并生成新回复：

- 如果用户是在提问、呼叫你、或需要回复，请输出 "##[interrupt]##" 然后直接开始回复
- 如果用户只是在自言自语、背景噪音、不需要回复，请输出 "##[no_reply]##"

示例：
用户: "你在吗？" → ##[interrupt]##我在的，有什么事吗？
用户: "主播好厉害" → ##[no_reply]##
用户: "今天天气怎么样" → ##[interrupt]##今天天气不错呢！"""
    
    async def _call_independent_llm(self, asr_text: str) -> dict:
        """调用独立 LLM"""
        import aiohttp
        
        prompt = f"""你是一个语音打断判断助手。请判断用户的语音输入是否需要打断当前播报并生成回复。

【用户语音】
{asr_text}

【判断规则】
- 用户是否在提问？
- 用户是否在呼叫？
- 用户是否在说重要的事情？
- 用户是否需要回复？

请返回 JSON 格式：
{{"interrupt": true, "reason": "用户在提问"}}
或
{{"interrupt": false, "reason": "用户在自言自语"}}"""
        
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
                            "interrupt": parsed.get("interrupt", False),
                            "reason": parsed.get("reason", "")
                        }
                    except json.JSONDecodeError:
                        if "true" in text.lower():
                            return {"interrupt": True, "reason": "从文本解析"}
                        return {"interrupt": False, "reason": "JSON 解析失败"}
                        
        except asyncio.TimeoutError:
            logger.warning("Independent LLM timeout")
            return {"interrupt": False, "reason": "超时"}
        except Exception as e:
            logger.error(f"Independent LLM error: {e}")
            return {"interrupt": False, "reason": str(e)}
    
    async def _trigger_interrupt(self, asr_text: str, llm_response: str = "") -> bool:
        """触发打断"""
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
        """重置打断状态"""
        self._is_interrupted = False
    
    @property
    def is_interrupted(self) -> bool:
        return self._is_interrupted


def get_asr_interrupt_module() -> ASRInterruptModule:
    return ASRInterruptModule.get_instance()
