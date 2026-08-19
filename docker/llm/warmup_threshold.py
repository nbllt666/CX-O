"""二分定位 vLLM prefix cache 的 prompt 长度阈值。

用不同长度的 user padding，找到命中（第2轮 <100ms）的最小总 token 数。
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


def tokenize_len(messages):
    body = {"model": MODEL, "messages": messages, "add_special_tokens": True}
    req = urllib.request.Request(
        f"http://127.0.0.1:8002/tokenize", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req)
        return len(json.loads(resp.read().decode()).get("tokens", []))
    except Exception:
        return None


def main():
    agent = get_agent_config("default") or {}
    system = agent.get("system_prompt", "")
    base = [{"role": "system", "content": system}]

    # 构造不同 pad 的 user 消息，精确测 token 数与命中
    print("=== pad 长度 -> token 数 -> 第2轮 TTFT ===")
    for pad_len in [8, 10, 11, 12, 13, 14, 15, 16, 18, 20, 22, 24, 26, 28, 30]:
        msgs = list(base)
        if pad_len:
            msgs.append({"role": "user", "content": "好的" * (pad_len // 2)})
        msgs.append({"role": "user", "content": "你好"})
        n = tokenize_len(msgs)
        r1 = measure(msgs)
        r2 = measure(msgs)
        hit = "✅" if r2 < 100 else " "
        print(f"  pad={pad_len:2d}: tokens={n}  r1={r1:.0f}ms r2={r2:.0f}ms {hit}")


if __name__ == "__main__":
    main()
