"""验证修复方案：system + 固定 assistant 占位(使前缀≥353) → 不同 user 后缀都能命中。

场景：
1. 预热: [system, assistant占位, user=你好]
2. 生产: [system, assistant占位, user=<真实不同文本>]  共享 [system+占位] 前缀
观察生产请求(不同 user)是否命中前缀缓存。
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


def tokenize_len(messages):
    body = {"model": MODEL, "messages": messages, "add_special_tokens": True}
    req = urllib.request.Request(
        "http://127.0.0.1:8002/tokenize", data=json.dumps(body).encode(),
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

    # 固定占位：assistant 简短确认语（无害）
    PLACEHOLDER = "好的，我明白了。请问有什么需要帮助的吗？"
    # 扩充占位到 system+占位 ≥ 353 tokens
    # 先测当前
    base_placeholder = [{"role": "system", "content": system}, {"role": "assistant", "content": PLACEHOLDER}]
    n = tokenize_len(base_placeholder + [{"role": "user", "content": "你好"}])
    print(f"占位基础结构 token 数（含 user）: {n}")

    # 扩增占位，确保前缀 ≥ 353
    filler = " 我在这里，随时待命。" * 3
    PLACEHOLDER_FULL = PLACEHOLDER + filler
    prefix_msgs = [{"role": "system", "content": system}, {"role": "assistant", "content": PLACEHOLDER_FULL}]
    n_prefix = tokenize_len(prefix_msgs)
    print(f"扩增后前缀 token 数（不含 user）: {n_prefix}")

    # 预热（固定 user=你好）
    warm_msgs = prefix_msgs + [{"role": "user", "content": "你好"}]
    print("=== 预热 5 轮 ===")
    for i in range(5):
        print(f"  round{i+1}: {measure(warm_msgs):.0f}ms")

    # 生产（不同 user 后缀）
    print("=== 生产不同 user 后缀（共享前缀）===")
    for text in ["你好", "今天天气怎么样", "帮我算一下3+5", "讲个笑话吧", "北京明天会下雨吗"]:
        m = prefix_msgs + [{"role": "user", "content": text}]
        ttft = measure(m)
        print(f"  user='{text[:12]}': TTFT={ttft:.0f}ms")


if __name__ == "__main__":
    main()
