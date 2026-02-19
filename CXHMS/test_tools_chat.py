"""
测试 Agent 列出工具
"""
import asyncio
import httpx
import json

async def test_chat():
    request_body = {
        "message": "你有什么工具可以使用？请列出所有可用工具。",
        "agent_id": "default",
        "stream": True
    }
    
    print("发送请求...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            "http://localhost:8000/api/chat/stream",
            json=request_body
        ) as response:
            print(f"响应状态: {response.status_code}\n")
            
            full_content = ""
            async for line in response.aiter_lines():
                if line.startswith('data: '):
                    try:
                        data = json.loads(line[6:])
                        if data.get('type') == 'content':
                            content = data.get('content', '')
                            full_content += content
                            print(content, end='', flush=True)
                        elif data.get('type') == 'done':
                            print("\n\n[完成]")
                    except:
                        pass
            
            print("\n" + "=" * 80)
            print("完整回复：")
            print("=" * 80)
            print(full_content)

if __name__ == "__main__":
    asyncio.run(test_chat())
