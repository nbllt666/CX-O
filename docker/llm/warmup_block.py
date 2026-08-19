"""精确验证：sliding attention 模型的 prefix cache block 对齐假设。

通过加入不同长度的 padding，观察 TTFT 命中规律，确定可缓存 block 边界。
每次测量只发 2 轮：第 2 轮若命中说明该长度可缓存。
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
    base = [{"role": "system", "content": system}]

    print("=== A 结构 + 不同 pad 长度：2 轮（第2轮命中=可缓存）===")
    for pad_len in range(0, 21):
        msgs = list(base)
        if pad_len:
            # 用 user 消息 padding，贴近真实场景
            msgs.append({"role": "user", "content": "好" * pad_len})
        msgs.append({"role": "user", "content": "你好"})

        r1 = measure(msgs)
        r2 = measure(msgs)
        hit = "✅" if r2 < 100 else " "
        print(f"  pad={pad_len:2d}: r1={r1:.0f}ms r2={r2:.0f}ms {hit}")


if __name__ == "__main__":
    main()
