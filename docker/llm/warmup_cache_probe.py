"""通过 usage.prompt_tokens_details.cached_tokens 诊断 A/B 结构的 prefix cache 命中。

结论判定：
- A 结构 [system, user]：cached_tokens≈0 → cache 完全 miss
- B 结构 [system+HISTORY+user]：cached_tokens≈prompt 总长 → cache 命中
"""
import json
import sys
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
    body = {
        "model": MODEL, "messages": messages, "stream": True, "max_tokens": max_tokens,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(VLLM, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = __import__("time").monotonic()
    first_ms = None
    usage = None
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
        if obj.get("usage"):
            usage = obj["usage"]
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        if delta.get("content") and first_ms is None:
            first_ms = (__import__("time").monotonic() - t0) * 1000
    return first_ms, usage


def main():
    agent = get_agent_config("default") or {}
    system = agent.get("system_prompt", "")

    msgs_2 = [{"role": "system", "content": system}, {"role": "user", "content": "你好"}]
    msgs_6 = [{"role": "system", "content": system}] + HISTORY + [{"role": "user", "content": "那晚上呢？"}]

    print("=== A: [system, user] 2 条 ===")
    for i in range(3):
        ttft, usage = measure(msgs_2)
        u = usage or {}
        ptd = u.get("prompt_tokens_details") or {}
        print(f"  round{i+1}: TTFT={ttft:.1f}ms prompt={u.get('prompt_tokens')} cached={ptd.get('cached_tokens')}")

    print("=== B: [system+HISTORY+user] 6 条 ===")
    for i in range(3):
        ttft, usage = measure(msgs_6)
        u = usage or {}
        ptd = u.get("prompt_tokens_details") or {}
        print(f"  round{i+1}: TTFT={ttft:.1f}ms prompt={u.get('prompt_tokens')} cached={ptd.get('cached_tokens')}")


if __name__ == "__main__":
    main()
