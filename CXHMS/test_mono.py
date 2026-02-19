#!/usr/bin/env python3
"""测试 mono 工具"""
import requests
import json
import sys

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
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return False

if __name__ == "__main__":
    # 测试 mono 工具
    test_stream_chat("请记住我的名字是张三，使用mono工具保持这个信息")
    
    # 测试计算器
    test_stream_chat("请计算 123 * 456 等于多少？")
    
    # 测试 datetime
    test_stream_chat("现在是什么时间？")
    
    # 测试 random
    test_stream_chat("请生成一个1到100之间的随机数")
