"""用服务端真实路径测量 build_messages(is_realtime_voice=True) 产出的消息 token 数。

用途（Task A 验证辅助）：
- 直接构造 VLLMClient 对 vLLM /v1/tokenize 发请求（与生产同 host/model）。
- 输出：当前实时语音 messages 的 token 数；以及追加固定 padding 后的 token 数。
- 确认 padding 是否把完整 messages 补足到 >=353 tokens（vLLM prefix cache 写入/命中阈值）。

用法:
    python docker/llm/tokenize_check.py
"""
import asyncio
import sys

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")

from server.config import get_settings
from server.chat_helpers import get_agent_config
try:  # padding 常量在修改前不存在，容错以便 before/after 都可运行
    from server.prompt_builder import build_messages, REALTIME_VOICE_PROMPT_PADDING
    HAS_PADDING = True
except ImportError:
    from server.prompt_builder import build_messages
    REALTIME_VOICE_PROMPT_PADDING = ""
    HAS_PADDING = False
from server.core.utils import get_shared_http_client


async def count_tokens(client, model: str, messages) -> dict:
    """POST /tokenize 返回 {'count': N, 'max_model_len': M} 或错误。"""
    payload = {"model": model, "messages": messages, "add_special_tokens": True}
    for endpoint in ("/tokenize", "/v1/tokenize"):
        try:
            resp = await client.post(
                f"http://127.0.0.1:8002{endpoint}", json=payload, timeout=30.0
            )
        except Exception as e:
            return {"error": str(e)}
        if resp.status_code != 200:
            continue
        data = resp.json()
        return {"endpoint": endpoint, "count": data.get("count"), "max_model_len": data.get("max_model_len")}
    return {"error": f"HTTP {resp.status_code}: {resp.text[:300]}"}


async def main():
    settings = get_settings()
    agent = get_agent_config("default") or {}
    model = settings.config.llm.model
    print(f"model: {model}")

    client = get_shared_http_client()

    for user_text in ["你好", "今天天气怎么样"]:
        messages = build_messages(agent, None, None, user_text, is_realtime_voice=True)
        chars = sum(len(m.get("content", "")) for m in messages)
        n_pad = 0
        if HAS_PADDING and REALTIME_VOICE_PROMPT_PADDING:
            n_pad = sum(
                len(m.get("content", ""))
                for m in messages
                if m.get("role") == "system" and REALTIME_VOICE_PROMPT_PADDING in m.get("content", "")
            )
        res = await count_tokens(client, model, messages)
        print(f"\n=== user_text='{user_text}' | messages={len(messages)} 条 | {chars} chars | padding已注入={bool(n_pad)} ===")
        print(f"  tokenize: {res}")
        if "count" in res:
            print(f"  count={res['count']}  >=353 ? {res['count'] >= 353}")


if __name__ == "__main__":
    asyncio.run(main())
