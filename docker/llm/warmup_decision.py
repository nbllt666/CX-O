"""决定性实验：用服务端生产消息（system608 + user）连续发 12 轮，观察 TTFT。

若恒定 224ms → prefix cache 对该序列 miss（前缀不同或 cache 未生效）
若从 224ms 降到 30ms → 首轮冷 cache，后续命中（服务端只是没预热对序列）
"""
import asyncio
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")

from server.chat_helpers import get_agent_config
from server.prompt_builder import build_messages

VLLM = "http://127.0.0.1:8002/v1/chat/completions"
MODEL = "gemma4-e4b"


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


def main():
    agent = get_agent_config("default") or {}
    messages = build_messages(agent, None, None, "你好", is_realtime_voice=True)
    sp_len = len((agent.get("system_prompt") or "").strip())
    chars = sum(len(m.get("content", "")) for m in messages)
    print(f"生产消息: {len(messages)} 条 | system={sp_len} chars | total={chars} chars")
    print("=== 连续 12 轮（urllib，完整前缀 608 字符）===")
    for i in range(12):
        ttft = measure_urllib(messages)
        print(f"  round{i+1}: TTFT={ttft:.1f}ms")


if __name__ == "__main__":
    main()
