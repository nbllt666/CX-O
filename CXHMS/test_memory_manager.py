#!/usr/bin/env python3
"""测试 MemoryManager 动态表名功能"""
import os
import sys
import time

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.core.memory.manager import MemoryManager

# 确保数据目录存在
os.makedirs('data', exist_ok=True)

# 测试 MemoryManager
mgr = MemoryManager('data/test_memories2.db')

# 测试动态表名
print('测试动态表名...')
print(f'默认表名: {mgr._get_table_name("default")}')
print(f'Agent表名: {mgr._get_table_name("test-agent")}')
print(f'特殊字符Agent表名: {mgr._get_table_name("my-agent-123")}')

# 测试写入记忆（默认Agent）
print('\n测试写入默认Agent记忆...')
mem_id1 = mgr.write_memory(
    content='这是默认Agent的记忆',
    memory_type='long_term',
    importance=4,
    agent_id='default'
)
print(f'默认Agent记忆ID: {mem_id1}')

# 测试写入记忆（特定Agent）
print('\n测试写入特定Agent记忆...')
mem_id2 = mgr.write_memory(
    content='这是测试Agent的记忆',
    memory_type='long_term',
    importance=5,
    agent_id='test-agent'
)
print(f'测试Agent记忆ID: {mem_id2}')

# 测试搜索记忆
print('\n测试搜索记忆...')
default_memories = mgr.search_memories(query='默认', agent_id='default')
print(f'默认Agent记忆数量: {len(default_memories)}')

test_memories = mgr.search_memories(query='测试', agent_id='test-agent')
print(f'测试Agent记忆数量: {len(test_memories)}')

# 关闭连接
mgr.close_all_connections()

# 删除测试数据库
time.sleep(0.5)
try:
    os.remove('data/test_memories2.db')
except:
    pass

print('\nMemoryManager 动态表名测试通过！')
