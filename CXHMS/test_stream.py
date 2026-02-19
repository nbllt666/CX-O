#!/usr/bin/env python3
"""测试流式聊天端点"""
import requests
import json
import sys

def test_stream_chat():
    url = "http://localhost:8000/api/chat/stream"
    data = {
        "message": "你有什么工具可以使用？请列出所有可用工具。",
        "agent_id": "default"
    }
    
    print(f"发送请求到: {url}")
    print(f"消息: {data['message']}")
    print("-" * 60)
    
    try:
        response = requests.post(url, json=data, stream=True, timeout=120)
        response.raise_for_status()
        
        full_content = []
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    json_str = line_str[6:]  # 去掉 'data: ' 前缀
                    if json_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(json_str)
                        if 'content' in chunk:
                            content = chunk['content']
                            print(content, end='', flush=True)
                            full_content.append(content)
                        elif 'error' in chunk:
                            print(f"\n[错误] {chunk['error']}")
                    except json.JSONDecodeError:
                        pass
        
        print("\n" + "-" * 60)
        print("完整回复:")
        print(''.join(full_content))
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_stream_chat()
    sys.exit(0 if success else 1)
