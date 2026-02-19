"""
测试流式聊天和工具调用功能
"""
import asyncio
import aiohttp
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


async def test_stream_chat():
    """测试流式聊天功能"""
    base_url = "http://localhost:8000"
    
    print("=" * 60)
    print("测试流式聊天和工具调用功能")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        # 1. 测试健康检查
        print("\n1. 测试健康检查...")
        async with session.get(f"{base_url}/health") as response:
            data = await response.json()
            print(f"   状态: {data.get('status')}")
            print(f"   服务: {data.get('services', {})}")
        
        # 2. 获取 Agent 列表
        print("\n2. 获取 Agent 列表...")
        async with session.get(f"{base_url}/api/agents") as response:
            agents = await response.json()
            print(f"   可用 Agent: {len(agents)}")
            for agent in agents[:3]:
                print(f"   - {agent.get('name')}: {agent.get('description', '无描述')}")
        
        # 3. 创建新会话并测试流式聊天
        print("\n3. 测试流式聊天...")
        
        # 使用默认 agent
        request_data = {
            "message": "你好，请介绍一下你自己",
            "agent_id": "default",
            "stream": True
        }
        
        print(f"   发送消息: {request_data['message']}")
        print("   等待响应...")
        
        async with session.post(
            f"{base_url}/api/chat/stream",
            json=request_data,
            timeout=aiohttp.ClientTimeout(total=60)
        ) as response:
            if response.status != 200:
                print(f"   ❌ 错误: HTTP {response.status}")
                error_text = await response.text()
                print(f"   详情: {error_text}")
                return False
            
            print("   ✅ 连接成功，开始接收流式数据...")
            
            message_count = 0
            tool_calls = []
            content_chunks = []
            
            # 读取流式响应
            async for line in response.content:
                line = line.decode('utf-8').strip()
                
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        msg_type = data.get('type')
                        
                        if msg_type == 'session':
                            print(f"   会话ID: {data.get('session_id')}")
                        
                        elif msg_type == 'content':
                            chunk = data.get('content', '')
                            content_chunks.append(chunk)
                            message_count += 1
                            if message_count <= 5:  # 只显示前5个
                                print(f"   [内容片段 {message_count}]: {chunk[:50]}...")
                        
                        elif msg_type == 'tool_call':
                            tool_call = data.get('tool_call', {})
                            tool_calls.append(tool_call)
                            print(f"   🔧 工具调用: {tool_call.get('name', 'unknown')}")
                            print(f"   参数: {tool_call.get('arguments', {})}...")
                        
                        elif msg_type == 'tool_start':
                            print(f"   ⚡ 开始执行工具: {data.get('tool_name')}")
                        
                        elif msg_type == 'tool_result':
                            result = data.get('result', {})
                            if isinstance(result, dict):
                                success = result.get('success', False)
                                print(f"   {'✅' if success else '❌'} 工具执行完成: {data.get('tool_name')} - 成功: {success}")
                            else:
                                print(f"   ✅ 工具执行完成: {data.get('tool_name')}")
                        
                        elif msg_type == 'done':
                            print(f"   ✅ 流式响应完成")
                            print(f"   总计: {len(content_chunks)} 个内容片段, {len(tool_calls)} 个工具调用")
                    
                    except json.JSONDecodeError:
                        continue
        
        # 4. 测试工具调用
        print("\n4. 测试工具调用...")
        
        # 尝试询问需要使用工具的问题
        tool_test_messages = [
            "设置一个5秒后的提醒",
            "搜索所有包含'测试'的记忆",
            "调用助手"
        ]
        
        for test_message in tool_test_messages[:1]:  # 只测试第一个
            print(f"\n   测试消息: {test_message}")
            
            request_data = {
                "message": test_message,
                "agent_id": "default",
                "stream": True
            }
            
            async with session.post(
                f"{base_url}/api/chat/stream",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status != 200:
                    print(f"   ❌ 错误: HTTP {response.status}")
                    continue
                
                tool_calls_count = 0
                
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            
                            if data.get('type') == 'tool_call':
                                tool_calls_count += 1
                                tool_name = data.get('tool_call', {}).get('name', 'unknown')
                                print(f"   🔧 检测到工具调用: {tool_name}")
                            
                            elif data.get('type') == 'done':
                                if tool_calls_count > 0:
                                    print(f"   ✅ 工具调用测试成功! 检测到 {tool_calls_count} 个工具调用")
                                else:
                                    print(f"   ℹ️  未检测到工具调用（可能 Agent 未配置工具）")
                        
                        except json.JSONDecodeError:
                            continue
        
        # 5. 获取上下文统计
        print("\n5. 获取上下文统计...")
        async with session.get(f"{base_url}/api/context/stats") as response:
            if response.status == 200:
                stats = await response.json()
                print(f"   总会话数: {stats.get('total_sessions', 0)}")
                print(f"   总消息数: {stats.get('total_messages', 0)}")
        
        # 6. 获取工具统计
        print("\n6. 获取工具统计...")
        async with session.get(f"{base_url}/api/tools/stats") as response:
            if response.status == 200:
                stats = await response.json()
                print(f"   总工具数: {stats.get('total_tools', 0)}")
                print(f"   启用工具数: {stats.get('enabled_tools', 0)}")
                if 'by_category' in stats:
                    print(f"   工具分类: {list(stats['by_category'].keys())}")
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
    return True


async def test_memory_functions():
    """测试记忆功能"""
    base_url = "http://localhost:8000"
    
    print("\n" + "=" * 60)
    print("测试记忆功能")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        # 1. 创建记忆
        print("\n1. 创建记忆...")
        memory_data = {
            "content": "这是一条测试记忆，用于验证记忆功能是否正常工作",
            "memory_type": "long_term",
            "importance": 4,
            "tags": ["test", "验证"],
            "metadata": {"source": "integration_test"}
        }
        
        async with session.post(f"{base_url}/api/memories", json=memory_data) as response:
            if response.status == 200:
                result = await response.json()
                print(f"   ✅ 记忆创建成功: {result.get('memory_id')}")
            else:
                print(f"   ❌ 记忆创建失败: HTTP {response.status}")
        
        # 2. 搜索记忆
        print("\n2. 搜索记忆...")
        async with session.post(f"{base_url}/api/memories/search", json={
            "query": "测试记忆",
            "limit": 5
        }) as response:
            if response.status == 200:
                result = await response.json()
                memories = result.get('memories', [])
                print(f"   找到 {len(memories)} 条相关记忆")
            else:
                print(f"   ❌ 搜索失败: HTTP {response.status}")
        
        # 3. 获取统计
        print("\n3. 获取记忆统计...")
        async with session.get(f"{base_url}/api/memories/stats") as response:
            if response.status == 200:
                stats = await response.json()
                print(f"   总记忆数: {stats.get('total_memories', 0)}")
                print(f"   长期记忆: {stats.get('by_type', {}).get('long_term', 0)}")
                print(f"   短期记忆: {stats.get('by_type', {}).get('short_term', 0)}")
    
    print("\n" + "=" * 60)
    print("记忆功能测试完成!")
    print("=" * 60)


async def main():
    """主函数"""
    print("正在连接后端服务...")
    print("请确保后端服务正在运行 (python -m uvicorn main:app --reload)")
    
    try:
        # 测试流式聊天
        await test_stream_chat()
        
        # 测试记忆功能
        await test_memory_functions()
        
    except aiohttp.ClientError as e:
        print(f"\n❌ 连接错误: {e}")
        print("请确保后端服务正在运行!")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
