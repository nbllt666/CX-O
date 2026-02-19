#!/usr/bin/env python3
"""测试流式聊天"""
import requests
import json

url = 'http://localhost:8000/api/chat/stream'
data = {'message': '你好', 'agent_id': 'default'}

print('测试流式聊天...')
response = requests.post(url, json=data, stream=True, timeout=60)
print(f'状态码: {response.status_code}')

if response.status_code == 200:
    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith('data: '):
                try:
                    chunk = json.loads(line_str[6:])
                    chunk_type = chunk.get('type')
                    if chunk_type == 'content':
                        print(f'[内容] {chunk.get("content", "")}', end='', flush=True)
                    elif chunk_type == 'thinking':
                        print(f'\n[思考] {chunk.get("content", "")}', end='', flush=True)
                    elif chunk_type == 'done':
                        print('\n[完成]')
                        break
                    elif chunk_type == 'tool_call':
                        print(f'\n[工具调用] {chunk}')
                except:
                    pass
else:
    print(f'错误: {response.text[:200]}')
