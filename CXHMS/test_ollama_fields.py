#!/usr/bin/env python3
"""测试 Ollama 流式响应的所有字段"""
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
all_fields = set()
for line in response.iter_lines():
    if line:
        data = json.loads(line)
        message = data.get('message', {})
        all_fields.update(message.keys())
        count += 1
        if count >= 5:
            break

print('所有字段:', all_fields)
print()
for i in range(5):
    response = requests.post(url, json=data, stream=True, timeout=30)
    for line in response.iter_lines():
        if line:
            data = json.loads(line)
            print(f'Line {i}: {data}')
            break
