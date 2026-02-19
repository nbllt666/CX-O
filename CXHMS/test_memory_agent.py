#!/usr/bin/env python3
"""测试记忆管理模型 API"""
import requests
import json

def test_memory_agent():
    url = "http://localhost:8000/api/memory-agent/chat/stream"
    data = {
        "message": "请显示记忆库的统计信息"
    }
    
    print(f"测试记忆管理模型 API")
    print(f"URL: {url}")
    print(f"发送消息: {data['message']}")
    print("-" * 60)
    
    try:
        response = requests.post(url, json=data, stream=True, timeout=120)
        print(f"状态码: {response.status_code}")
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                print(f"原始行: {line_str[:100]}...")
                if line_str.startswith('data: '):
                    json_str = line_str[6:]
                    if json_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(json_str)
                        if chunk.get('type') == 'content':
                            print(chunk['content'], end='', flush=True)
                        elif chunk.get('type') == 'tool_call':
                            print(f"\n[工具调用] {chunk['tool_call']}")
                        elif chunk.get('type') == 'tool_result':
                            print(f"\n[工具结果] {chunk['result']}")
                    except json.JSONDecodeError as e:
                        print(f"JSON解析错误: {e}")
        
        print("\n" + "-" * 60)
        print("测试完成!")
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    test_memory_agent()
