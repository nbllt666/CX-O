"""验证纯 system 级 padding 方案（不改变消息结构，只扩增 system prompt）。

在 system prompt 末尾追加 padding，确保 system + user ≥ 353 tokens。
消息结构保持不变：仍是 [system, user] 2 条。
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

    # 在 system prompt 末尾追加 padding（纯文本，无角色变化）
    # padding 内容：简短但无害的"继续对话"引导
    PAD = "请继续对话。好的，我明白了。" * 2  # ~36 chars ≈ 30 tokens
    system_padded = system + "\n\n" + PAD

    msgs_padded = [{"role": "system", "content": system_padded}, {"role": "user", "content": "你好"}]
    n = tokenize_len(msgs_padded)
    print(f"扩增 system 后 token 数: {n}")

    print("=== 预热 5 轮 ===")
    for i in range(5):
        print(f"  round{i+1}: {measure(msgs_padded):.0f}ms")

    print("=== 生产不同 user（共享 system 前缀）===")
    for text in ["你好", "今天天气怎么样", "帮我算一下3+5", "讲个笑话吧", "北京明天会下雨吗"]:
        m = [{"role": "system", "content": system_padded}, {"role": "user", "content": text}]
        ttft = measure(m)
        print(f"  user='{text[:12]}': TTFT={ttft:.0f}ms")


if __name__ == "__main__":
    main()