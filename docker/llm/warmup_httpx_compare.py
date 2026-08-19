"""对照实验：urllib vs httpx(AsyncClient) 直测同一 vLLM 消息的 TTFT。

目的：定位"服务端 httpx stream_chat TTFT 231-1093ms vs urllib 直测 30ms"的差异来源。
- 若 httpx 同样 30ms → 差异在消息结构（生产 build_messages 前缀与预热不一致）
- 若 httpx 明显偏高 → httpx SSE 流解析/代理检测存在额外开销
"""
import asyncio
import json
import time
import urllib.request

VLLM = "http://127.0.0.1:8002/v1/chat/completions"
MODEL = "gemma4-e4b"

# 与 warmup_test.py 相同的完整 system_prompt + 历史（预热已建立该前缀）
FULL_SYSTEM = open(
    "docker/llm/warmup_test.py", encoding="utf-8"
).read().split('FULL_SYSTEM = """', 1)[1].split('"""', 1)[0]

HISTORY = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你的吗？"},
    {"role": "user", "content": "今天天气怎么样"},
    {"role": "assistant", "content": "今天天气不错，适合出门散步。"},
]
USER_MSG = "那晚上呢？"


def build_messages():
    return [{"role": "system", "content": FULL_SYSTEM}] + HISTORY + [{"role": "user", "content": USER_MSG}]


def measure_urllib(messages):
    body = {"model": MODEL, "messages": messages, "stream": True, "max_tokens": 16}
    req = urllib.request.Request(
        VLLM, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    t0 = time.monotonic()
    first_ms = None
    resp = urllib.request.urlopen(req)
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        token = delta.get("content") or ""
        if token and first_ms is None:
            first_ms = (time.monotonic() - t0) * 1000
    return first_ms


async def measure_httpx(messages):
    import httpx

    async with httpx.AsyncClient(trust_env=False, proxy=None) as client:
        t0 = time.monotonic()
        first_ms = None
        async with client.stream(
            "POST", VLLM,
            json={"model": MODEL, "messages": messages, "stream": True, "max_tokens": 16},
            timeout=30.0,
        ) as resp:
            async for line in resp.aiter_lines():
                if line and line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        content = chunk["choices"][0]["delta"].get("content", "")
                        if content and first_ms is None:
                            first_ms = (time.monotonic() - t0) * 1000
                    except Exception:
                        continue
    return first_ms


async def main():
    msgs = build_messages()
    print("=== urllib 直测（3 轮）===")
    for i in range(3):
        ttft = measure_urllib(msgs)
        print(f"  round{i+1}: TTFT={ttft:.1f}ms")

    print("=== httpx AsyncClient 直测（3 轮）===")
    for i in range(3):
        ttft = await measure_httpx(msgs)
        print(f"  round{i+1}: TTFT={ttft:.1f}ms")


if __name__ == "__main__":
    asyncio.run(main())
