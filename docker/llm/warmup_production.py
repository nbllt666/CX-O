"""验证生产场景：预热建立缓存后，真实同款请求第 1 轮能否命中。

场景 A: 预热 [system, user] (341) → 真实 [system, user] (341) 是否命中？
场景 B: 预热 [system, pad, user] (353+) → 真实 [system, pad, user] (353+) 第 1 轮命中？
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")
from server.chat_helpers import get_agent_config

VLLM = "http://127.0.0.1:8002/v1/chat/completions"
MODEL = "gemma4-e4b"


def measure(messages, max_tokens=8):
    body = {"model": MODEL, "messages": messages, "stream": True, "max_tokens": max_tokens}
    req = urllib.request.Request(VLLM, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
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
        if line[5:].strip() == b"[DONE]":
            break
        try:
            obj = json.loads(line[5:].strip())
        except Exception:
            continue
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content") and first_ms is None:
            first_ms = (time.monotonic() - t0) * 1000
    return first_ms


def main():
    agent = get_agent_config("default") or {}
    system = agent.get("system_prompt", "")
    msgs_plain = [{"role": "system", "content": system}, {"role": "user", "content": "你好"}]
    pad = "好的好的好的好的好的好的好的"
    msgs_padded = [{"role": "system", "content": system}, {"role": "user", "content": pad}, {"role": "user", "content": "你好"}]

    print("=== 场景 A: 预热 [system,user] 5 轮 → 再测第 1 轮 ===")
    for i in range(5):
        print(f"  预热 round{i+1}: {measure(msgs_plain):.0f}ms")
    print(f"  [真实第1轮] {measure(msgs_plain):.0f}ms")

    print("=== 场景 B: 预热 [system,pad,user] 5 轮 → 再测第 1 轮 ===")
    for i in range(5):
        print(f"  预热 round{i+1}: {measure(msgs_padded):.0f}ms")
    print(f"  [真实第1轮] {measure(msgs_padded):.0f}ms")


if __name__ == "__main__":
    main()
