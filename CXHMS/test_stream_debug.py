"""
调试流式聊天
"""
import asyncio
import httpx
import json

async def test_stream():
    request_body = {
        "model": "qwen3-vl:8b",
        "messages": [{"role": "user", "content": "你好"}],
        "stream": True,
        "options": {
            "temperature": 0.7,
            "num_predict": 4096
        }
    }
    
    print("发送请求到 Ollama...")
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            async with client.stream(
                "POST",
                "http://localhost:11434/api/chat",
                json=request_body
            ) as response:
                print(f"响应状态: {response.status_code}")
                
                chunk_count = 0
                async for line in response.aiter_lines():
                    chunk_count += 1
                    if line:
                        print(f"\n[块 {chunk_count}] {line[:200]}...")
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            done = data.get("done", False)
                            print(f"  content: {content[:50] if content else 'None'}")
                            print(f"  done: {done}")
                            
                            if done:
                                print("\n收到 done=True，结束")
                                break
                        except json.JSONDecodeError as e:
                            print(f"  JSON解析错误: {e}")
                    else:
                        print(f"[块 {chunk_count}] (空行)")
                
                print(f"\n总计收到 {chunk_count} 个块")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_stream())
