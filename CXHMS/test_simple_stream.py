"""
简化的流式聊天测试
"""
import asyncio
import aiohttp
import json
import sys

async def simple_stream_test():
    base_url = "http://localhost:8000"
    
    print("测试流式聊天...")
    
    request_data = {
        "message": "你好，请介绍你自己",
        "agent_id": "default",
        "stream": True
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/api/chat/stream",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                print(f"响应状态: {response.status}")
                
                if response.status != 200:
                    print(f"错误: HTTP {response.status}")
                    error = await response.text()
                    print(f"详情: {error[:500]}")
                    return False
                
                chunk_count = 0
                async for chunk in response.content:
                    chunk_count += 1
                    text = chunk.decode('utf-8').strip()
                    
                    if not text:
                        continue
                    
                    print(f"块 {chunk_count}: {text[:100]}...")
                    
                    if chunk_count > 5:
                        print("收到多个块，测试成功!")
                        return True
                
                print("未收到任何数据")
                return False
                
    except Exception as e:
        print(f"异常: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(simple_stream_test())
    print(f"\n测试结果: {'成功' if success else '失败'}")
    sys.exit(0 if success else 1)
