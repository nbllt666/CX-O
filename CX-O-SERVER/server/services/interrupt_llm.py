"""
server/services/interrupt_llm.py
================================
打断判定共用的独立小模型调用助手与打断模块公共基类。

封装「POST Ollama /api/generate + JSON 解析 + 文本关键词兜底 + 超时/异常降级」，
供 asr_interrupt 与 agent_interrupt_user 两个打断模块复用，统一降级语义。

正常返回：{"decision": "CONTINUE|IGNORE|INTERRUPT", "reason": "..."}
"""
import asyncio
import inspect
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class InterruptModuleBase:
    """打断模块公共基类。

    收敛自 asr_interrupt.ASRInterruptModule 与 agent_interrupt_user.AgentInterruptUser
    的重复实现：会话上下文读取、独立小模型配置与调用。

    子类职责：
      - __init__ 中调用 super().__init__() 完成会话/上下文/独立模型配置初始化
      - 实现 _build_independent_prompt(asr_text) 构造独立模型判定 prompt
      - 可用类属性 _independent_timeout 覆盖独立模型调用超时（默认 3.0s）
    """

    _independent_timeout: float = 3.0
    # M7（第五轮）: 主 LLM 打断判定调用的超时上限。无超时的话，LLM 挂起会
    # 永久占用 `_interrupt_sem` 槽位/后台任务，最终打断判定静默失效、任务累积。
    _main_llm_timeout: float = 15.0

    def __init__(self):
        self._session_id: Optional[str] = None
        self._context_manager: Any = None
        self.independent_llm_config = {
            "enabled": False,
            "model": "qwen2.5:1.5b",
            "endpoint": "http://localhost:11434",
        }

    def set_session_id(self, session_id: str):
        self._session_id = session_id

    def set_context_manager(self, context_manager: Any):
        self._context_manager = context_manager

    def _get_context(self) -> list:
        if self._context_manager and self._session_id:
            return self._context_manager.get_context(self._session_id)
        return []

    def _build_independent_prompt(self, asr_text: str) -> str:
        raise NotImplementedError("子类必须实现 _build_independent_prompt")

    async def _call_independent_llm(self, asr_text: str) -> dict:
        """调用独立小模型，返回 JSON decision。统一 HTTP 调用、JSON 解析与兜底降级。"""
        prompt = self._build_independent_prompt(asr_text)
        return await call_ollama_decision(
            endpoint=self.independent_llm_config["endpoint"],
            model=self.independent_llm_config["model"],
            prompt=prompt,
            timeout=self._independent_timeout,
        )

    async def _call_main_llm(self, user_content: str) -> Optional[str]:
        """调用主 LLM 返回响应文本；client 不可用或响应异常时返回 None。

        收敛自 asr_interrupt 与 agent_interrupt_user 的主 LLM 判定前缀：
        取主 LLM → 拼接会话上下文+用户消息 → chat(stream=False) → 取响应文本。
        """
        try:
            from server.dependencies import get_llm_client

            llm = get_llm_client()
            # H4: get_context 返回会话真实存储列表，直接 append 会把打断判定的
            # ASR 原文永久写进对话历史（绕过 max_history 截断且每次重复注入）。
            # 用浅拷贝隔离，判定结束后不污染真实上下文。
            messages = list(self._get_context())
            messages.append({"role": "user", "content": user_content})
            response = await asyncio.wait_for(
                llm.chat(messages=messages, stream=False),
                timeout=self._main_llm_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("主 LLM 打断判定超时（%ss），按不可判定降级", self._main_llm_timeout)
            return None
        except Exception as e:
            logger.warning(f"主 LLM 不可用/调用失败: {e}")
            return None
        if not response or response.error:
            return None
        return response.content or ""

    async def _invoke_callback(self, callback: Any, *args) -> None:
        """统一回调分发：判别协程/普通函数并 try/except 包裹。

        收敛自 asr_interrupt._trigger_interrupt 与 agent_interrupt_user.interrupt_user
        的「回调同步/异步分发 + 异常兜底」重复实现。
        """
        if not callback:
            return
        try:
            if inspect.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"回调执行错误: {e}")


async def call_ollama_decision(
    endpoint: str,
    model: str,
    prompt: str,
    timeout: float = 3.0,
) -> dict:
    """调用 Ollama 独立小模型返回三态打断判定。

    语义（与两个打断模块原有兜底逐分支对齐）：
      - JSON 可解析 → 取 decision（缺失默认 IGNORE）
      - JSON 失败但文本含 INTERRUPT/IGNORE → 文本关键词兜底
      - JSON 失败且无关键词 → CONTINUE
      - 超时 → CONTINUE
      - 其他异常 → IGNORE
    """
    import aiohttp

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{endpoint}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                result = await response.json()
                text = result.get("response", "")
                try:
                    parsed = json.loads(text)
                    return {
                        "decision": parsed.get("decision", "IGNORE"),
                        "reason": parsed.get("reason", ""),
                    }
                except json.JSONDecodeError:
                    if "INTERRUPT" in text:
                        return {"decision": "INTERRUPT", "reason": "文本解析"}
                    if "IGNORE" in text:
                        return {"decision": "IGNORE", "reason": "文本解析"}
                    return {"decision": "CONTINUE", "reason": "JSON解析失败"}
    except asyncio.TimeoutError:
        logger.warning("独立判定 LLM 超时")
        return {"decision": "CONTINUE", "reason": "超时"}
    except Exception as e:
        logger.error(f"独立判定 LLM 错误: {e}")
        return {"decision": "IGNORE", "reason": str(e)}
