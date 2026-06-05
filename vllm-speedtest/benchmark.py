"""
vLLM 性能测试脚本
测试首包延迟 (TTFT) 和生成速度 (tokens/s)
"""

import requests
import time
import json
import argparse
from datetime import datetime

API_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "gemma4-e4b"

# 约 1k token 的输入文本
DEFAULT_PROMPT = """请详细分析人工智能技术在医疗健康领域的应用现状和未来发展趋势。具体包括以下几个方面：

1. 医学影像诊断：AI如何辅助医生进行CT、MRI、X光等医学影像的分析和诊断，目前有哪些成熟的商业化应用，准确率如何，存在哪些挑战。

2. 药物研发：AI在药物发现、分子设计、临床试验优化等方面的应用，有哪些成功案例，对传统药物研发流程带来了哪些变革。

3. 个性化医疗：基于基因组学、电子病历等数据，AI如何实现精准医疗和个性化治疗方案推荐。

4. 医疗机器人：手术机器人、康复机器人、护理机器人的发展现状和技术突破。

5. 远程医疗和健康管理：AI驱动的远程诊断、健康监测、慢病管理应用。

6. 挑战与展望：数据隐私、算法可解释性、监管政策、伦理问题等挑战，以及未来5-10年的发展预测。

请逐一详细阐述，给出具体数据和案例支持你的分析。
"""

def benchmark(prompt: str, max_tokens: int = 1000, stream: bool = True) -> dict:
    """执行单次基准测试"""
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": stream
    }

    headers = {"Content-Type": "application/json"}

    start_time = time.time()
    first_token_time = None
    total_tokens = 0
    output_text = ""

    if stream:
        with requests.post(API_URL, headers=headers, json=payload, stream=True) as resp:
            for line in resp.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            chunk = json.loads(data)
                            if chunk.get('choices') and chunk['choices'][0].get('delta', {}).get('content'):
                                if first_token_time is None:
                                    first_token_time = time.time()
                                content = chunk['choices'][0]['delta']['content']
                                output_text += content
                                total_tokens += 1
                        except:
                            pass
    else:
        resp = requests.post(API_URL, headers=headers, json=payload)
        result = resp.json()
        total_tokens = result.get('usage', {}).get('completion_tokens', 0)
        output_text = result['choices'][0]['message']['content']
        first_token_time = time.time()

    end_time = time.time()

    ttft = (first_token_time - start_time) * 1000 if first_token_time else 0
    total_time = (end_time - start_time) * 1000
    tps = total_tokens / (total_time / 1000) if total_time > 0 else 0

    return {
        "total_time_ms": round(total_time, 2),
        "ttft_ms": round(ttft, 2),
        "output_tokens": total_tokens,
        "tokens_per_second": round(tps, 2),
        "output_preview": output_text[:200] + "..." if len(output_text) > 200 else output_text
    }

def main():
    parser = argparse.ArgumentParser(description='vLLM 性能测试')
    parser.add_argument('--rounds', type=int, default=2, help='测试轮数')
    parser.add_argument('--max-tokens', type=int, default=1000, help='最大输出 tokens')
    parser.add_argument('--prompt', type=str, default=None, help='自定义提示词')
    args = parser.parse_args()

    prompt = args.prompt or DEFAULT_PROMPT

    print("=" * 60)
    print(f"vLLM Gemma4-E4B INT8 性能测试")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    print(f"API: {API_URL}")
    print(f"模型: {MODEL}")
    print(f"测试轮数: {args.rounds}")
    print(f"最大输出: {args.max_tokens} tokens")
    print("=" * 60)

    results = []
    for i in range(1, args.rounds + 1):
        print(f"\n第 {i} 轮测试:")
        print("-" * 40)
        result = benchmark(prompt, max_tokens=args.max_tokens, stream=True)
        results.append(result)

        print(f"首包延迟 (TTFT): {result['ttft_ms']:.0f} ms")
        print(f"总耗时: {result['total_time_ms']:.0f} ms")
        print(f"输出 tokens: {result['output_tokens']}")
        print(f"生成速度: {result['tokens_per_second']:.2f} tokens/s")

    # 统计
    print("\n" + "=" * 60)
    print("测试汇总")
    print("=" * 60)

    avg_ttft = sum(r['ttft_ms'] for r in results) / len(results)
    avg_tps = sum(r['tokens_per_second'] for r in results) / len(results)

    print(f"平均首包延迟: {avg_ttft:.0f} ms")
    print(f"平均生成速度: {avg_tps:.2f} tokens/s")
    print(f"最快首包延迟: {min(r['ttft_ms'] for r in results):.0f} ms")
    print(f"最快生成速度: {max(r['tokens_per_second'] for r in results):.2f} tokens/s")

    # 首轮 vs 后续（预热效果）
    if len(results) > 1:
        first_ttft = results[0]['ttft_ms']
        later_avg_ttft = sum(r['ttft_ms'] for r in results[1:]) / (len(results) - 1)
        speedup = (first_ttft - later_avg_ttft) / first_ttft * 100 if first_ttft > 0 else 0
        print(f"\n预热效果: 首包延迟降低 {speedup:.1f}%")

if __name__ == "__main__":
    main()
