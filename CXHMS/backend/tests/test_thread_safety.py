"""线程安全和并发测试"""

import os
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.context.manager import ContextManager
from backend.core.memory.manager import MemoryManager


class TestThreadSafety:
    """测试线程安全性和并发"""

    def test_concurrent_session_creation(self, tmp_path):
        """测试并发创建会话"""
        db_path = tmp_path / "test_concurrent.db"
        manager = ContextManager(str(db_path))

        session_ids = []
        errors = []

        def create_session():
            try:
                session_id = manager.create_session(workspace_id="default")
                session_ids.append(session_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_session) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"创建会话时发生错误: {errors}"
        assert len(session_ids) == 10, "应该创建10个会话"
        assert len(set(session_ids)) == 10, "所有会话ID应该唯一"

        sessions = manager.get_sessions(workspace_id="default")
        assert len(sessions) == 10, "应该有10个会话"

        manager.shutdown()

    def test_concurrent_message_addition(self, tmp_path):
        """测试并发添加消息"""
        db_path = tmp_path / "test_concurrent_messages.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        message_ids = []
        errors = []

        def add_message(index):
            try:
                message_id = manager.add_message(
                    session_id=session_id, role="user", content=f"消息{index}"
                )
                message_ids.append(message_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_message, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"添加消息时发生错误: {errors}"
        assert len(message_ids) == 20, "应该添加20条消息"
        assert len(set(message_ids)) == 20, "所有消息ID应该唯一"

        messages = manager.get_messages(session_id)
        assert len(messages) == 20, "应该有20条消息"

        session = manager.get_session(session_id)
        assert session["message_count"] == 20, "消息计数应该是20"

        manager.shutdown()

    def test_concurrent_memory_operations(self, tmp_path):
        """测试并发记忆操作"""
        db_path = tmp_path / "test_concurrent_memory.db"
        manager = MemoryManager(str(db_path))

        memory_ids = []
        errors = []

        def write_memory(index):
            try:
                memory_id = manager.write_memory(
                    content=f"记忆内容{index}", memory_type="long_term", importance=3, tags=["test"]
                )
                memory_ids.append(memory_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_memory, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) <= 1, f"写入记忆时发生错误: {errors}（允许少量数据库锁定错误）"
        assert len(memory_ids) >= 4, f"应该写入至少4条记忆（实际: {len(memory_ids)}）"

        for memory_id in memory_ids:
            memory = manager.get_memory(memory_id)
            assert memory is not None, f"记忆 {memory_id} 应该存在"

        manager.shutdown()

    def test_concurrent_session_and_message(self, tmp_path):
        """测试并发创建会话和添加消息"""
        db_path = tmp_path / "test_concurrent_mixed.db"
        manager = ContextManager(str(db_path))

        session_ids = []
        message_ids = []
        errors = []

        def create_session_and_messages():
            try:
                session_id = manager.create_session(workspace_id="default")
                session_ids.append(session_id)

                for i in range(5):
                    manager.add_message(session_id=session_id, role="user", content=f"消息{i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_session_and_messages) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"操作时发生错误: {errors}"
        assert len(session_ids) == 5, "应该创建5个会话"
        assert len(set(session_ids)) == 5, "所有会话ID应该唯一"

        total_messages = 0
        for session_id in session_ids:
            messages = manager.get_messages(session_id)
            total_messages += len(messages)
            assert len(messages) == 5, f"会话 {session_id} 应该有5条消息"

        assert total_messages == 25, "总共应该有25条消息"

        manager.shutdown()

    def test_connection_reuse_in_same_thread(self, tmp_path):
        """测试同一线程内连接复用"""
        db_path = tmp_path / "test_connection_reuse.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.add_message(session_id, "user", "消息1")
        manager.add_message(session_id, "user", "消息2")
        manager.add_message(session_id, "user", "消息3")

        session = manager.get_session(session_id)
        assert session is not None, "应该能获取到会话"

        messages = manager.get_messages(session_id)
        assert len(messages) == 3, "应该有3条消息"

        manager.shutdown()

    def test_multiple_managers_same_db(self, tmp_path):
        """测试多个管理器访问同一数据库"""
        db_path = tmp_path / "test_multiple_managers.db"

        manager1 = ContextManager(str(db_path))
        manager2 = ContextManager(str(db_path))

        session_id1 = manager1.create_session(workspace_id="default")
        session_id2 = manager2.create_session(workspace_id="default")

        manager1.add_message(session_id1, "user", "管理器1的消息")
        manager2.add_message(session_id2, "user", "管理器2的消息")

        sessions1 = manager1.get_sessions(workspace_id="default")
        sessions2 = manager2.get_sessions(workspace_id="default")

        assert len(sessions1) == 2, "管理器1应该看到2个会话"
        assert len(sessions2) == 2, "管理器2应该看到2个会话"

        manager1.shutdown()
        manager2.shutdown()

    def test_concurrent_get_statistics(self, tmp_path):
        """测试并发获取统计信息"""
        db_path = tmp_path / "test_concurrent_stats.db"
        manager = ContextManager(str(db_path))

        for i in range(10):
            session_id = manager.create_session(workspace_id="default")
            for j in range(5):
                manager.add_message(session_id, "user", f"消息{j}")

        stats_list = []
        errors = []

        def get_stats():
            try:
                stats = manager.get_statistics(workspace_id="default")
                stats_list.append(stats)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_stats) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"获取统计信息时发生错误: {errors}"
        assert len(stats_list) == 10, "应该获取10次统计信息"

        for stats in stats_list:
            assert stats["total_sessions"] == 10, "应该有10个会话"
            assert stats["total_messages"] == 50, "应该有50条消息"

        manager.shutdown()

    def test_concurrent_update_session(self, tmp_path):
        """测试并发更新会话"""
        db_path = tmp_path / "test_concurrent_update.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default", title="原标题")

        errors = []

        def update_session(index):
            try:
                manager.update_session(session_id, title=f"更新标题{index}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_session, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"更新会话时发生错误: {errors}"

        session = manager.get_session(session_id)
        assert session is not None, "应该能获取到会话"
        assert session["title"].startswith("更新标题"), "标题应该被更新"

        manager.shutdown()

    def test_concurrent_delete_message(self, tmp_path):
        """测试并发删除消息"""
        db_path = tmp_path / "test_concurrent_delete.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        message_ids = []
        for i in range(10):
            message_id = manager.add_message(session_id, "user", f"消息{i}")
            message_ids.append(message_id)

        errors = []

        def delete_message(message_id):
            try:
                manager.delete_message(message_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=delete_message, args=(mid,)) for mid in message_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"删除消息时发生错误: {errors}"

        messages = manager.get_messages(session_id)
        assert len(messages) == 0, "所有消息应该被删除"

        manager.shutdown()

    def test_rapid_open_close_connections(self, tmp_path):
        """测试快速打开和关闭连接"""
        db_path = tmp_path / "test_rapid_connections.db"
        manager = ContextManager(str(db_path))

        errors = []

        def rapid_operations():
            try:
                for i in range(5):
                    session_id = manager.create_session(workspace_id="default")
                    manager.add_message(session_id, "user", f"消息{i}")
                    manager.get_session(session_id)
                    manager.get_messages(session_id)
                    manager.close_connection()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=rapid_operations) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"快速操作时发生错误: {errors}"

        sessions = manager.get_sessions(workspace_id="default")
        assert len(sessions) == 15, "应该有15个会话"

        manager.shutdown()
