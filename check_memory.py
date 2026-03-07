"""详细检查记忆系统"""
import asyncio
import httpx


async def check_memory():
    cxhms_url = "http://127.0.0.1:8000"
    
    print("=== 检查记忆系统 ===\n")
    
    # 1. 保存一条测试记忆
    print("1. 保存测试记忆...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{cxhms_url}/api/memories",
                json={
                    "content": "测试记忆：用户叫张三，是软件工程师，喜欢编程和音乐",
                    "metadata": {"type": "test", "user": "张三"}
                }
            )
            print(f"  状态: {response.status_code}")
            if response.status_code in [200, 201]:
                result = response.json()
                print(f"  保存成功: {result}")
            else:
                print(f"  失败: {response.text}")
    except Exception as e:
        print(f"  错误: {e}")
    
    # 等待一下让记忆写入
    await asyncio.sleep(2)
    
    # 2. 搜索记忆
    print("\n2. 搜索记忆...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{cxhms_url}/api/memories/search",
                json={"query": "张三"}
            )
            print(f"  状态: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                print(f"  找到: {len(result.get('results', []))} 条")
                for r in result.get('results', [])[:3]:
                    print(f"    - {r.get('content', '')[:50]}...")
            else:
                print(f"  失败: {response.text}")
    except Exception as e:
        print(f"  错误: {e}")
    
    # 3. 列出所有记忆
    print("\n3. 列出所有记忆...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{cxhms_url}/api/memories?limit=10")
            print(f"  状态: {response.status_code}")
            if response.status_code == 200:
                result = response.json()
                print(f"  总数: {result.get('total', 0)}")
                for m in result.get('memories', [])[:5]:
                    print(f"    - {m.get('content', '')[:50]}...")
            else:
                print(f"  失败: {response.text}")
    except Exception as e:
        print(f"  错误: {e}")


if __name__ == "__main__":
    asyncio.run(check_memory())
