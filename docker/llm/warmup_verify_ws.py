"""验证：padding 后，不同 user 文本是否都命中 prefix cache。

与 warmup_verify_system_pad.py 同逻辑，但用服务端真实 build_messages 结构。
预热 user='你好'，然后测不同 user 文本的 TTFT。
"""
import json
import sys
import time
import urllib.request

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")
from server.chat_helpers import get_agent_config
from server.prompt_builder import build_messages, REALTIME_VOICE_PROMPT_PADDING

VLLM = "http://127.0.0.1:8002/v1/chat/completions"
MODEL = "gemma4-e4b"


def measure(messages, max_tokens=16):
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

    # 预热 user='你好'（同构生产）
    warm_msgs = build_messages(agent, None, None, "你好", is_realtime_voice=True)
    print(f"预热结构: {len(warm_msgs)} 条, system={len(warm_msgs[0]['content'])} chars")
    print("=== 预热 3 轮 ===")
    for i in range(3):
        print(f"  round{i+1}: TTFT={measure(warm_msgs):.0f}ms")

    print("=== 不同 user 文本（共享 system+padding 前缀）===")
    for text in ["你好", "今天天气怎么样", "帮我算一下3+5", "讲个笑话吧", "我想听首歌"]:
        m = build_messages(agent, None, None, text, is_realtime_voice=True)
        ttft = measure(m)
        print(f"  user='{text[:12]}': TTFT={ttft:.0f}ms")

    # 验证 padding 是否真的在 system 中
    print(f"\npadding 在 system 中: {'REALTIME_VOICE_PROMPT_PADDING' in 'x'}")
    print(f"system 前缀一致性: {warm_msgs[0]['content'].startswith(agent.get('system_prompt','')[:50])}")


if __name__ == "__main__":
    main()
