"""交叉实验：B 结构(带 HISTORY)先建立 system 前缀缓存，再测 A 结构是否命中。

若 A 结构命中（30ms）→ vLLM 前缀缓存按 token 前缀工作，A 能复用 B 建立的前缀
若 A 结构仍 230ms → vLLM 对 A 结构(短 prompt)不缓存/不命中（需换思路）
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")
from server.chat_helpers import get_agent_config

VLLM = "http://127.0.0.1:8002/v1/chat/completions"
MODEL = "gemma4-e4b"

HISTORY = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你的吗？"},
    {"role": "user", "content": "今天天气怎么样"},
    {"role": "assistant", "content": "今天天气不错，适合出门散步。"},
]


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
    msgs_2 = [{"role": "system", "content": system}, {"role": "user", "content": "你好"}]
    msgs_6 = [{"role": "system", "content": system}] + HISTORY + [{"role": "user", "content": "那晚上呢？"}]

    print("=== 1. 先 B 结构建立 system 前缀缓存（3 轮）===")
    for i in range(3):
        print(f"  B round{i+1}: TTFT={measure(msgs_6):.1f}ms")

    print("=== 2. 立刻测 A 结构（观察是否命中 B 建立的前缀）===")
    for i in range(3):
        print(f"  A round{i+1}: TTFT={measure(msgs_2):.1f}ms")

    print("=== 3. 再测 B 结构（确认缓存仍在）===")
    for i in range(2):
        print(f"  B round{i+1}: TTFT={measure(msgs_6):.1f}ms")

    print("=== 4. 再测 A 结构 ===")
    for i in range(3):
        print(f"  A round{i+1}: TTFT={measure(msgs_2):.1f}ms")


if __name__ == "__main__":
    main()
