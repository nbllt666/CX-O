"""
测试 Agent 工具列表
"""
import asyncio
import httpx
import json

async def test():
    request_body = {
        "message": "你有什么工具可以使用？请列出所有可用工具。",
        "agent_id": "default",
        "stream": True
    }
    
    print("发送请求...\n")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                "http://localhost:8000/api/chat/stream",
                json=request_body
            ) as response:
                print(f"响应状态: {response.status_code}\n")
                
                full_content = ""
                chunk_count = 0
                
                async for line in response.aiter_lines():
                    chunk_count += 1
                    if line.startswith('data: '):
                        try:
                            data = json.loads(line[6:])
                            msg_type = data.get('type')
                            
                            if msg_type == 'session':
                                print(f"[Session] {data.get('session_id')}")
                            elif msg_type == 'content':
                                content = data.get('content', '')
                                full_content += content
                                print(content, end='', flush=True)
                            elif msg_type == 'tool_call':
                                print(f"\n[Tool Call] {data.get('tool_call')}")
                            elif msg_type == 'done':
                                print(f"\n[Done]")
                                break
                        except Exception as e:
                            print(f"[Error parsing] {e}")
                
                print(f"\n\n总计 {chunk_count} 个数据块")
                print("\n" + "=" * 80)
                print("完整回复:")
                print("=" * 80)
                print(full_content)
                
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
