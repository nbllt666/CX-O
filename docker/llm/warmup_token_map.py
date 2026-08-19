"""测量各 user 文本的完整 token 数与 TTFT，定位 block 对齐边界。

目标：找出 vLLM sliding attention prefix cache 的精确 block 边界，
确认 padding 后哪些 user 长度命中/不命中。
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")
from server.chat_helpers import get_agent_config
from server.prompt_builder import build_messages

VLLM = "http://127.0.0.1:8002"
MODEL = "gemma4-e4b"


def tokenize_len(messages):
    body = {"model": MODEL, "messages": messages, "add_special_tokens": True}
    req = urllib.request.Request(
        f"{VLLM}/tokenize", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req)
        return len(json.loads(resp.read().decode()).get("tokens", []))
    except Exception:
        return None


def measure(messages, max_tokens=16):
    body = {"model": MODEL, "messages": messages, "stream": True, "max_tokens": max_tokens}
    req = urllib.request.Request(
        f"{VLLM}/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
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
    texts = [
        "你好", "今天天气怎么样", "帮我算一下3+5", "讲个笑话吧", "我想听首歌",
        "你叫什么名字", "给我讲个故事", "什么是人工智能", "怎么才能学好英语",
        "帮我安排一下明天的行程",
    ]
    print(f"{'user 文本':<16} {'tokens':>6}  TTFT")
    print("-" * 40)
    for text in texts:
        m = build_messages(agent, None, None, text, is_realtime_voice=True)
        n = tokenize_len(m)
        ttft = measure(m)
        hit = "✅" if ttft < 120 else "❌"
        print(f"{text[:14]:<16} {n:>6}  {ttft:.0f}ms {hit}")


if __name__ == "__main__":
    main()
