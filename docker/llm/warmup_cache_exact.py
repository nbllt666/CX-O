"""精确读取 cached_tokens：确认 A 结构缓存 miss 的机制。

用法：对同一 A 结构连续 5 轮，读取每轮 usage.cached_tokens。
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")
from server.chat_helpers import get_agent_config

VLLM = "http://127.0.0.1:8002/v1/chat/completions"
MODEL = "gemma4-e4b"


def measure_with_usage(messages, max_tokens=8):
    body = {
        "model": MODEL, "messages": messages, "stream": True, "max_tokens": max_tokens,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(VLLM, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    first_ms = None
    last_usage = None
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
        if obj.get("usage"):
            last_usage = obj["usage"]
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content") and first_ms is None:
            first_ms = (time.monotonic() - t0) * 1000
    return first_ms, last_usage


def main():
    agent = get_agent_config("default") or {}
    system = agent.get("system_prompt", "")
    msgs_2 = [{"role": "system", "content": system}, {"role": "user", "content": "你好"}]

    print("=== A 结构 [system, user] 连续 6 轮（读取 cached_tokens）===")
    for i in range(6):
        ttft, usage = measure_with_usage(msgs_2)
        u = usage or {}
        ptd = u.get("prompt_tokens_details") or {}
        print(f"  round{i+1}: TTFT={ttft:.1f}ms prompt={u.get('prompt_tokens')} cached={ptd.get('cached_tokens')}")


if __name__ == "__main__":
    main()
