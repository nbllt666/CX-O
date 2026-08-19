"""验证 vLLM prefix caching：预热完整 system_prompt 后，同前缀 TTFT 是否下降。

流程：
1. 直接用完整 system_prompt 测 TTFT（基线）
2. 发一次完整响应预热（建立前缀 KV cache）
3. 再次用同 system_prompt 测 TTFT（应命中缓存，显著下降）
"""
import json
import time
import urllib.request

VLLM = "http://127.0.0.1:8002/v1/chat/completions"

FULL_SYSTEM = """你是默认助手，一位热情、可靠、随和的AI伙伴。请始终用中文、以自然亲切的口吻回答用户的问题，语气贴近日常交流，避免生硬。

你可以使用以下工具帮助用户：

### 基础工具
1. calculator - 数学计算工具，支持基本运算、三角函数、对数等
2. datetime - 获取当前日期和时间
3. random - 生成随机数
4. json_format - 格式化JSON字符串

### 记忆与上下文工具
5. write_long_term_memory - 写入长期记忆，保存用户的重要信息、偏好、事件等
6. search_all_memories - 搜索所有记忆，检索与当前话题相关的历史信息
7. call_assistant - 调用记忆管理模型，获取专业处理结果
8. set_alarm - 设置定时提醒，在指定时间后提醒用户
9. mono - 保持信息在上下文中，跨多轮对话记住重要信息

使用原则：
- 需要计算/时间/日期/随机数/JSON格式化时，首选对应工具，不要自己心算或编造
- 用户提到的重要偏好、事实、事件，主动调用 write_long_term_memory 保存
- 用户问及之前聊过的事情时，先 search_all_memories 检索
- 用户要求定闹钟/提醒时，调用 set_alarm
- 回答清晰直接，先给结论再给补充；不确定时坦诚说明，不编造"""

USER_MSG = "你好，今天天气怎么样？"


def measure_ttft(messages, max_tokens=64):
    body = {
        "model": "gemma4-e4b",
        "messages": messages,
        "stream": True,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        VLLM,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    first_ms = None
    first_text = ""
    tokens = 0
    resp = urllib.request.urlopen(req)
    while True:
        line = resp.readline()
        if not line:
            break
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[5:].strip()
        if payload == b"[DONE]":
            break
        try:
            obj = json.loads(payload)
        except Exception:
            continue
        delta = (obj.get("choices") or [{}])[0].get("delta") or {}
        token = delta.get("content") or ""
        if token:
            if first_ms is None:
                first_ms = (time.monotonic() - t0) * 1000
                first_text = token
            tokens += 1
    total = (time.monotonic() - t0) * 1000
    return first_ms, total, first_text, tokens


def main():
    msgs = [{"role": "system", "content": FULL_SYSTEM}, {"role": "user", "content": USER_MSG}]

    print("=== 1. 基线（未预热前缀）===")
    for i in range(2):
        ttft, total, first, n = measure_ttft(msgs)
        print(f"  round{i+1}: TTFT={ttft:.0f}ms total={total:.0f}ms first='{first}'")

    print("=== 2. 预热：发一次完整响应（建立前缀 KV cache）===")
    ttft, total, first, n = measure_ttft(msgs, max_tokens=64)
    print(f"  warmup: TTFT={ttft:.0f}ms total={total:.0f}ms tokens={n}")

    print("=== 3. 预热后（应命中 prefix cache）===")
    for i in range(3):
        ttft, total, first, n = measure_ttft(msgs)
        print(f"  round{i+1}: TTFT={ttft:.0f}ms total={total:.0f}ms first='{first}'")


if __name__ == "__main__":
    main()
