"""单次请求 TTFT 验证：等价于生产 WS 实时语音首次请求。

用途（Task A4 验证辅助）：
- 用服务端真实路径 build_messages(is_realtime_voice=True) + VLLMClient.stream_chat
  发一次请求（与生产 WS 完全同构的 prompt 结构），测 first-token 延迟。
- 该路径与 CX-O-SERVER 语音前缀预热建立的 prefix cache 完全同构，
  因此单次请求即可判定"预热后新会话首次请求"是否命中（TTFT <=100ms）。
- 不依赖 WS/ASR/TTS，只测 LLM 环节，规避 TTS(8094) 离线与 GPU 竞争对全链路的干扰。

用法:
    python docker/llm/ttft_single.py [user_text]
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
    user_text = sys.argv[1] if len(sys.argv) > 1 else "你好"
    settings = get_settings()
    agent = get_agent_config("default") or {}
    host = settings.config.llm.host
    model = settings.config.llm.model
    llm = VLLMClient(host=host, model=model, temperature=0.7, max_tokens=32768)

    get_shared_http_client()
    await asyncio.sleep(0.2)

    messages = build_messages(agent, None, None, user_text, is_realtime_voice=True)
    chars = sum(len(m.get("content", "")) for m in messages)
    print(f"user_text='{user_text}' | messages={len(messages)} 条 | {chars} chars")

    t0 = time.monotonic()
    tokens = []
    async for chunk in llm.stream_chat(messages=messages, temperature=0.7, max_tokens=16):
        if isinstance(chunk, dict):
            continue
        tokens.append(chunk)
    total = (time.monotonic() - t0) * 1000
    print(f"TTFT: first-token 见上方 DIAG-TTFT 日志；总耗时 total={total:.1f}ms tokens={len(tokens)}")


if __name__ == "__main__":
    asyncio.run(main())
