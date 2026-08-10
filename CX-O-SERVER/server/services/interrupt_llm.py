"""
server/services/interrupt_llm.py
================================
打断判定共用的独立小模型调用助手。

封装「POST Ollama /api/generate + JSON 解析 + 文本关键词兜底 + 超时/异常降级」，
供 asr_interrupt 与 agent_interrupt_user 两个打断模块复用，统一降级语义。

正常返回：{"decision": "CONTINUE|IGNORE|INTERRUPT", "reason": "..."}
"""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


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