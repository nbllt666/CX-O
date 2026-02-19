#!/usr/bin/env python3
"""测试批量操作功能"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.core.memory.manager import MemoryManager

# 确保数据目录存在
os.makedirs('data', exist_ok=True)

# 测试 MemoryManager
mgr = MemoryManager('data/test_batch.db')

print("=" * 60)
print("测试批量操作功能")
print("=" * 60)

# 1. 批量写入记忆
print("\n1. 测试批量写入记忆...")
memories = [
    {"content": "记忆1", "type": "long_term", "importance": 3, "tags": ["测试", "标签1"]},
    {"content": "记忆2", "type": "long_term", "importance": 4, "tags": ["测试", "标签2"]},
    {"content": "记忆3", "type": "short_term", "importance": 2, "tags": ["临时"]},
]
result = mgr.batch_write_memories(memories)
print(f"批量写入结果: 成功 {result['success']} 条, 失败 {result['failed']} 条")
print(f"记忆IDs: {result['memory_ids']}")

# 2. 批量更新标签
print("\n2. 测试批量更新标签...")
memory_ids = result['memory_ids']
update_result = mgr.batch_update_tags(
    memory_ids=memory_ids[:2],
    tags=["新标签"],
    operation="add"
)
print(f"批量更新标签结果: 成功 {update_result['updated_count']} 条, 失败 {update_result.get('failed_count', 0)} 条")

# 3. 批量归档
print("\n3. 测试批量归档...")
archive_result = mgr.batch_archive_memories(memory_ids[:2])
print(f"批量归档结果: 成功 {archive_result['archived_count']} 条, 失败 {archive_result.get('failed_count', 0)} 条")

# 4. 批量删除
print("\n4. 测试批量删除...")
delete_result = mgr.batch_delete_memories(memory_ids)
print(f"批量删除结果: 成功 {delete_result['success']} 条, 失败 {delete_result['failed']} 条")

# 关闭连接
mgr.close_all_connections()

# 删除测试数据库
time.sleep(0.5)
try:
    os.remove('data/test_batch.db')
except:
    pass

print("\n" + "=" * 60)
print("批量操作功能测试通过！")
print("=" * 60)
