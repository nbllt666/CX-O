"""探测 vLLM prefix cache 的最小工作 prompt 长度。

从 341 tokens（A 结构）开始，逐步增加 padding 直到 cache 命中（TTFT 降到 30ms）。
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

    # 基准：A 结构（341 tokens）
    msgs_2 = [{"role": "system", "content": system}, {"role": "user", "content": "你好"}]

    # 测试：在 system 与 user 之间插入不同长度的 padding assistant 消息
    # 观察 TTFT 何时降到 30ms
    for padding_len in [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45]:
        pad_tokens = "好的。" * padding_len  # 每个"好的。"约 3 tokens
        msgs = [{"role": "system", "content": system}]
        if pad_tokens:
            msgs.append({"role": "assistant", "content": pad_tokens.strip(".")})
        msgs.append({"role": "user", "content": "你好"})

        # 连续 3 轮取最后 2 轮的最小值（排除冷启动）
        results = []
        for i in range(3):
            results.append(measure(msgs))
        stable = min(results[1:])
        hit = "✅" if stable < 100 else " "
        print(f"  pad={padding_len:3d} (~{341 + padding_len*3} tokens): {results[0]:.0f}/{results[1]:.0f}/{results[2]:.0f}ms  stable={stable:.0f}ms {hit}")


if __name__ == "__main__":
    main()