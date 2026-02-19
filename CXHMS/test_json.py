#!/usr/bin/env python3
"""测试 JSON 格式化工具"""
import requests
import json

def test_stream_chat(message):
    url = "http://localhost:8000/api/chat/stream"
    data = {
        "message": message,
        "agent_id": "default"
    }
    
    print(f"\n{'='*60}")
    print(f"发送消息: {message}")
    print("="*60)
    
    try:
        response = requests.post(url, json=data, stream=True, timeout=60)
        response.raise_for_status()
        
        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith('data: '):
                    json_str = line_str[6:]
                    if json_str == '[DONE]':
                        break
                    try:
                        chunk = json.loads(json_str)
                        if 'content' in chunk:
                            print(chunk['content'], end='', flush=True)
                    except:
                        pass
        
        print("\n" + "-" * 60)
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    # 测试 JSON 格式化
    test_stream_chat('请格式化这个JSON字符串：{"name":"张三","age":25,"city":"北京"}')
