#!/usr/bin/env python3
"""测试记忆写入工具"""
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
    # 测试1: 写入记忆
    test_stream_chat("请记住：我喜欢吃川菜，特别是麻婆豆腐。")
    
    # 测试2: 搜索记忆
    test_stream_chat("我喜欢吃什么菜？")
    
    # 测试3: 设置提醒
    test_stream_chat("请设置一个5秒后的提醒，内容是'该休息了'")
    
    # 测试4: mono 保持上下文
    test_stream_chat("请记住我的名字是张三，使用mono工具保持这个信息")
