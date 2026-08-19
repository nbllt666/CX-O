"""验证：A/B 结构的 system 前缀 token 是否一致。

用 vLLM 的 chat template + tokenizer 对 A 和 B 结构分别 token 化，
比较前 N 个 token（system_prompt 部分）是否完全相同。
"""
import json
import sys
import urllib.request

sys.path.insert(0, r"c:\CX-O\CX-O-SERVER")
from server.chat_helpers import get_agent_config

VLLM = "http://127.0.0.1:8002"
MODEL = "gemma4-e4b"

HISTORY = [
    {"role": "user", "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你的吗？"},
    {"role": "user", "content": "今天天气怎么样"},
    {"role": "assistant", "content": "今天天气不错，适合出门散步。"},
]


def tokenize(messages):
    """调用 vLLM 的 /tokenize 接口。"""
    body = {"model": MODEL, "messages": messages, "add_special_tokens": True}
    req = urllib.request.Request(
        f"{VLLM}/tokenize", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode())


def main():
    agent = get_agent_config("default") or {}
    system = agent.get("system_prompt", "")

    msgs_2 = [{"role": "system", "content": system}, {"role": "user", "content": "你好"}]
    msgs_6 = [{"role": "system", "content": system}] + HISTORY + [{"role": "user", "content": "那晚上呢？"}]

    r2 = tokenize(msgs_2)
    r6 = tokenize(msgs_6)
    t2 = r2.get("tokens", [])
    t6 = r6.get("tokens", [])
    print(f"A tokens: {len(t2)}")
    print(f"B tokens: {len(t6)}")

    # 比较共享前缀长度
    common = 0
    for a, b in zip(t2, t6):
        if a == b:
            common += 1
        else:
            break
    print(f"共享前缀 token 数: {common}")
    print(f"前 5 token A: {t2[:5]}")
    print(f"前 5 token B: {t6[:5]}")
    # 找第一个不同位置
    if common < min(len(t2), len(t6)):
        print(f"第一个不同位置: {common}")
        print(f"  A: ...{t2[max(0,common-2):common+3]}")
        print(f"  B: ...{t6[max(0,common-2):common+3]}")


if __name__ == "__main__":
    main()
