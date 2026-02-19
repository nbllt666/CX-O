#!/usr/bin/env python3
"""测试 Ollama 流式响应"""
import requests
import json

url = 'http://localhost:11434/api/chat'
data = {
    'model': 'qwen3-vl:8b',
    'messages': [{'role': 'user', 'content': '你好'}],
    'stream': True
}

response = requests.post(url, json=data, stream=True, timeout=30)
count = 0
for line in response.iter_lines():
    if line:
        data = json.loads(line)
        message = data.get('message', {})
        print(f'Line {count}:')
        print(f'  content: {message.get("content", "")[:50]}')
        print(f'  thinking: {message.get("thinking", "")[:50]}')
        print(f'  reasoning_content: {message.get("reasoning_content", "")[:50]}')
        count += 1
        if count >= 10:
            break
