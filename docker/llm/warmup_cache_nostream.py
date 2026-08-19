"""非流式请求获取 cached_tokens 决定性证据。

vLLM 0.22 流式响应可能不填充 prompt_tokens_details.cached_tokens，
改用非流式请求读取 usage 字段。
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


def measure_nostream(messages, max_tokens=8):
    body = {"model": MODEL, "messages": messages, "stream": False, "max_tokens": max_tokens}
    req = urllib.request.Request(VLLM, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    resp = urllib.request.urlopen(req)
    obj = json.loads(resp.read().decode())
    elapsed = (time.monotonic() - t0) * 1000
    usage = obj.get("usage") or {}
    ptd = usage.get("prompt_tokens_details") or {}
    return elapsed, usage, ptd


def main():
    agent = get_agent_config("default") or {}
    system = agent.get("system_prompt", "")
    msgs_2 = [{"role": "system", "content": system}, {"role": "user", "content": "你好"}]
    msgs_6 = [{"role": "system", "content": system}] + HISTORY + [{"role": "user", "content": "那晚上呢？"}]

    print("=== A: [system, user] 2 条（非流式）===")
    for i in range(3):
        el, usage, ptd = measure_nostream(msgs_2)
        print(f"  round{i+1}: {el:.1f}ms prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} cached={ptd.get('cached_tokens')}")

    print("=== B: [system+HISTORY+user] 6 条（非流式）===")
    for i in range(3):
        el, usage, ptd = measure_nostream(msgs_6)
        print(f"  round{i+1}: {el:.1f}ms prompt={usage.get('prompt_tokens')} completion={usage.get('completion_tokens')} cached={ptd.get('cached_tokens')}")


if __name__ == "__main__":
    main()
