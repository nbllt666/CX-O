"""
CXHMS 流式聊天和工具调用集成测试
"""
import asyncio
import aiohttp
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class CXHMSTester:
    """CXHMS 服务测试器"""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.results = []
    
    async def test_health_check(self, session: aiohttp.ClientSession) -> bool:
        """测试健康检查"""
        print("\n" + "=" * 60)
        print("1. 测试健康检查")
        print("=" * 60)
        
        try:
            async with session.get(f"{self.base_url}/health") as response:
                if response.status == 200:
                    data = await response.json()
                    print(f"✅ 服务状态: {data.get('status')}")
                    print(f"   服务名称: {data.get('service')}")
                    print(f"   版本: {data.get('version')}")
                    self.results.append(("健康检查", True, "服务运行正常"))
                    return True
                else:
                    print(f"❌ 健康检查失败: HTTP {response.status}")
                    self.results.append(("健康检查", False, f"HTTP {response.status}"))
                    return False
        except Exception as e:
            print(f"❌ 健康检查异常: {e}")
            self.results.append(("健康检查", False, str(e)))
            return False
    
    async def test_streaming_chat(self, session: aiohttp.ClientSession) -> bool:
        """测试流式聊天"""
        print("\n" + "=" * 60)
        print("2. 测试流式聊天")
        print("=" * 60)
        
        request_data = {
            "message": "你好，请用一句话介绍你自己",
            "agent_id": "default",
            "stream": True
        }
        
        print(f"📤 发送消息: {request_data['message']}")
        print("📥 等待响应...")
        
        try:
            async with session.post(
                f"{self.base_url}/api/chat/stream",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    print(f"❌ 流式聊天失败: HTTP {response.status}")
                    error_text = await response.text()
                    print(f"   详情: {error_text[:200]}")
                    self.results.append(("流式聊天", False, f"HTTP {response.status}"))
                    return False
                
                print("✅ 连接成功，开始接收流式数据...")
                
                content_chunks = 0
                session_id = None
                
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    
                    # 跳过空行
                    if not line:
                        continue
                    
                    print(f"   [调试] 收到原始数据: {repr(line)[:200]}")
                    
                    if not line.startswith("data: "):
                        print(f"   [警告] 数据不以 'data: ' 开头!")
                        continue
                    
                    try:
                        data = json.loads(line[6:])
                        msg_type = data.get('type')
                        
                        if msg_type == 'session':
                            session_id = data.get('session_id')
                            print(f"   会话ID: {session_id}")
                        
                        elif msg_type == 'content':
                            content_chunks += 1
                            if content_chunks == 1:
                                content_preview = data.get('content', '')[:100]
                                print(f"   [内容预览]: {content_preview}...")
                        
                        elif msg_type == 'done':
                            print(f"   ✅ 流式响应完成!")
                            print(f"   总计收到 {content_chunks} 个内容片段")
                    
                    except json.JSONDecodeError as e:
                        print(f"   [警告] JSON解析失败: {e}")
                        continue
                    except KeyError as e:
                        print(f"   [警告] KeyError: {e}")
                        continue
                    except Exception as e:
                        print(f"   [错误] 处理数据时出错: {e}")
                        continue
                
                if session_id:
                    print("✅ 流式聊天测试成功!")
                    self.results.append(("流式聊天", True, f"会话ID: {session_id}"))
                    return True
                else:
                    print("❌ 未收到会话ID")
                    self.results.append(("流式聊天", False, "未收到会话ID"))
                    return False
                    
        except Exception as e:
            print(f"❌ 流式聊天异常: {e}")
            self.results.append(("流式聊天", False, str(e)))
            return False
    
    async def test_direct_tool_call(self, session: aiohttp.ClientSession) -> bool:
        """测试直接工具调用"""
        print("\n" + "=" * 60)
        print("3. 测试直接工具调用")
        print("=" * 60)
        
        tool_request = {
            "name": "set_alarm",
            "arguments": {
                "seconds": 60,
                "message": "集成测试提醒"
            }
        }
        
        print("🔧 调用工具: set_alarm")
        print(f"   参数: {json.dumps(tool_request['arguments'], ensure_ascii=False)}")
        
        try:
            async with session.post(
                f"{self.base_url}/api/tools/call",
                json=tool_request,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    print(f"❌ 工具调用失败: HTTP {response.status}")
                    error_text = await response.text()
                    print(f"   详情: {error_text[:200]}")
                    self.results.append(("直接工具调用", False, f"HTTP {response.status}"))
                    return False
                
                result = await response.json()
                print(f"✅ 工具调用成功!")
                print(f"   结果: {json.dumps(result, ensure_ascii=False, indent=2)}")
                
                if result.get('success'):
                    alarm_id = result.get('result', {}).get('alarm_id', 'unknown')
                    print(f"   提醒ID: {alarm_id}")
                    self.results.append(("直接工具调用", True, f"alarm_id: {alarm_id}"))
                    return True
                else:
                    print("❌ 工具调用未成功")
                    self.results.append(("直接工具调用", False, "工具返回失败"))
                    return False
                    
        except Exception as e:
            print(f"❌ 工具调用异常: {e}")
            self.results.append(("直接工具调用", False, str(e)))
            return False
    
    async def test_context_stats(self, session: aiohttp.ClientSession) -> bool:
        """测试上下文统计"""
        print("\n" + "=" * 60)
        print("4. 测试上下文统计")
        print("=" * 60)
        
        try:
            async with session.get(f"{self.base_url}/api/context/stats") as response:
                if response.status == 200:
                    result = await response.json()
                    stats = result.get('statistics', {})
                    print(f"✅ 获取统计成功!")
                    print(f"   总会话数: {stats.get('total_sessions', 0)}")
                    print(f"   活动会话: {stats.get('active_sessions', 0)}")
                    print(f"   总消息数: {stats.get('total_messages', 0)}")
                    print(f"   平均消息/会话: {stats.get('avg_messages_per_session', 0):.2f}")
                    self.results.append(("上下文统计", True, f"会话: {stats.get('total_sessions', 0)}, 消息: {stats.get('total_messages', 0)}"))
                    return True
                else:
                    print(f"❌ 获取统计失败: HTTP {response.status}")
                    self.results.append(("上下文统计", False, f"HTTP {response.status}"))
                    return False
                    
        except Exception as e:
            print(f"❌ 获取统计异常: {e}")
            self.results.append(("上下文统计", False, str(e)))
            return False
    
    async def run_all_tests(self) -> bool:
        """运行所有测试"""
        print("\n" + "=" * 60)
        print("CXHMS 服务集成测试")
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"服务地址: {self.base_url}")
        print("=" * 60)
        
        async with aiohttp.ClientSession() as session:
            # 运行所有测试
            await self.test_health_check(session)
            await self.test_streaming_chat(session)
            await self.test_direct_tool_call(session)
            await self.test_context_stats(session)
        
        # 输出测试结果摘要
        print("\n" + "=" * 60)
        print("测试结果摘要")
        print("=" * 60)
        
        passed = 0
        failed = 0
        
        for test_name, success, details in self.results:
            status = "✅ 通过" if success else "❌ 失败"
            print(f"{status} | {test_name}: {details}")
            if success:
                passed += 1
            else:
                failed += 1
        
        print("=" * 60)
        print(f"总计: {passed + failed} 个测试, {passed} 个通过, {failed} 个失败")
        print("=" * 60)
        
        return failed == 0


async def main():
    """主函数"""
    print("正在测试 CXHMS 服务...")
    print("请确保后端服务正在运行!")
    
    tester = CXHMSTester()
    success = await tester.run_all_tests()
    
    if success:
        print("\n🎉 所有测试通过!")
        return 0
    else:
        print("\n❌ 部分测试失败!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
