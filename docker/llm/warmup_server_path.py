"""用服务端真实代码路径复现 WS 链路 LLM TTFT。

直接构造 VLLMClient（与 server 生产一致：host/model 来自 config.json），
通过 build_messages(is_realtime_voice=True) 生成生产消息，测 TTFT。

目的：确认生产请求（非并发）的 TTFT 是否为 30ms 级。
"""
import asyncio
import sys
import time

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")

from server.config import get_settings
from server.chat_helpers import get_agent_config
from server.prompt_builder import build_messages
from server.core.utils import get_shared_http_client
from server.core.llm.client import VLLMClient


async def main():
    settings = get_settings()
    agent = get_agent_config("default") or {}
    host = settings.config.llm.host
    model = settings.config.llm.model
    llm = VLLMClient(host=host, model=model, temperature=0.7, max_tokens=32768)
    print(f"agent: default | host: {host} | model: {model}")
    print(f"system_prompt 长度: {len((agent.get('system_prompt') or '').strip())}")

    # 预热 shared client（Windows httpx 首次构造 8s）
    get_shared_http_client()
    await asyncio.sleep(0.2)

    for user_text in ["你好", "今天天气怎么样"]:
        messages = build_messages(agent, None, None, user_text, is_realtime_voice=True)
        chars = sum(len(m.get("content", "")) for m in messages)
        print(f"\n=== user_text='{user_text}' | messages={len(messages)} 条 | {chars} chars ===")
        for i in range(3):
            t0 = time.monotonic()
            tokens = []
            async for chunk in llm.stream_chat(messages=messages, temperature=0.7, max_tokens=16):
                if isinstance(chunk, dict):
                    continue
                tokens.append(chunk)
            total = (time.monotonic() - t0) * 1000
            first = "".join(tokens)[:20]
            print(f"  round{i+1}: total={total:.1f}ms tokens={len(tokens)} first='{first}'")


if __name__ == "__main__":
    asyncio.run(main())
