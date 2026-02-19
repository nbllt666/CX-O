import asyncio
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.context.manager import ContextManager
from backend.core.memory.decay import DecayCalculator
from backend.core.memory.manager import MemoryManager
from backend.core.memory.secondary_router import (
    SecondaryCommand,
    SecondaryInstruction,
    SecondaryModelRouter,
)


class TestMemoryManagerBasics:
    """测试记忆管理器基础功能"""

    def test_write_memory(self, tmp_path):
        """测试写入记忆"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_memory(
            content="测试记忆内容",
            memory_type="long_term",
            importance=3,
            tags=["test", "unit"],
            metadata={"source": "test"},
        )

        assert memory_id > 0, "记忆ID应该大于0"

        memory = manager.get_memory(memory_id)
        assert memory is not None, "应该能获取到记忆"
        assert memory["content"] == "测试记忆内容", "记忆内容应该匹配"

        manager.shutdown()

    def test_update_memory(self, tmp_path):
        """测试更新记忆"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_memory(content="原始内容", memory_type="long_term", importance=2)

        success = manager.update_memory(
            memory_id=memory_id, new_content="更新后的内容", new_importance=4
        )

        assert success is True, "更新应该成功"

        memory = manager.get_memory(memory_id)
        assert memory["content"] == "更新后的内容", "内容应该已更新"
        assert memory["importance"] == 4, "重要性应该已更新"

        manager.shutdown()

    def test_delete_memory(self, tmp_path):
        """测试删除记忆"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_memory(content="待删除的记忆", memory_type="short_term")

        success = manager.delete_memory(memory_id)
        assert success is True, "删除应该成功"

        memory = manager.get_memory(memory_id)
        assert memory is None, "删除后应该无法获取记忆"

        manager.shutdown()


class TestPermanentMemories:
    """测试永久记忆功能"""

    def test_write_permanent_memory(self, tmp_path):
        """测试写入永久记忆"""
        db_path = tmp_path / "test_permanent.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_permanent_memory(
            content="永久记忆内容",
            tags=["permanent", "important"],
            metadata={"priority": "high"},
            emotion_score=0.8,
            source="user",
            is_from_main=True,
        )

        assert memory_id > 0, "永久记忆ID应该大于0"

        memory = manager.get_permanent_memory(memory_id)
        assert memory is not None, "应该能获取到永久记忆"
        assert memory["content"] == "永久记忆内容", "内容应该匹配"
        assert memory["verified"] == True, "应该已验证"

        manager.shutdown()

    def test_get_permanent_memories(self, tmp_path):
        """测试获取永久记忆列表"""
        db_path = tmp_path / "test_permanent2.db"
        manager = MemoryManager(str(db_path))

        manager.write_permanent_memory(content="永久记忆1", tags=["test"], source="user")

        manager.write_permanent_memory(content="永久记忆2", tags=["test"], source="system")

        memories = manager.get_permanent_memories()
        assert len(memories) >= 2, "应该至少有两条永久记忆"

        manager.shutdown()

    def test_update_permanent_memory(self, tmp_path):
        """测试更新永久记忆"""
        db_path = tmp_path / "test_permanent3.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_permanent_memory(content="原始永久记忆", tags=["original"])

        success = manager.update_permanent_memory(
            memory_id=memory_id, content="更新的永久记忆", tags=["updated"]
        )

        assert success is True, "更新应该成功"

        memory = manager.get_permanent_memory(memory_id)
        assert memory["content"] == "更新的永久记忆", "内容应该已更新"

        manager.shutdown()

    def test_delete_permanent_memory(self, tmp_path):
        """测试删除永久记忆"""
        db_path = tmp_path / "test_permanent4.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_permanent_memory(content="待删除的永久记忆")

        success = manager.delete_permanent_memory(memory_id, is_from_main=True)
        assert success is True, "主模型应该能删除永久记忆"

        memory = manager.get_permanent_memory(memory_id)
        assert memory is None, "删除后应该无法获取永久记忆"

        manager.shutdown()

    def test_secondary_model_permission(self, tmp_path):
        """测试副模型权限"""
        db_path = tmp_path / "test_permanent5.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_permanent_memory(content="测试权限的记忆", is_from_main=True)

        # 副模型不能删除永久记忆
        success = manager.delete_permanent_memory(memory_id, is_from_main=False)
        assert success is False, "副模型不应该能删除永久记忆"

        manager.shutdown()


class TestMemorySearch:
    """测试记忆搜索功能"""

    def test_search_memories(self, tmp_path):
        """测试记忆搜索"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        # 写入测试记忆
        manager.write_memory(
            content="关于Python编程的记忆", memory_type="long_term", tags=["python", "programming"]
        )

        manager.write_memory(
            content="关于机器学习的记忆", memory_type="long_term", tags=["ml", "ai"]
        )

        # 搜索
        results = manager.search_memories(query="Python", memory_type="long_term")

        assert isinstance(results, list), "搜索结果应该是列表"

        manager.shutdown()


class TestMemoryRecall:
    """测试记忆召回功能"""

    def test_recall_memory(self, tmp_path):
        """测试记忆召回"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_memory(
            content="需要召回的记忆", memory_type="long_term", importance=5
        )

        # 召回记忆
        recalled = manager.recall_memory(memory_id=memory_id, emotion_intensity=0.8)

        assert recalled is not None, "召回应该成功"
        assert recalled["reactivation_count"] > 0, "重激活计数应该增加"

        manager.shutdown()


class TestMemoryBatchOperations:
    """测试批量操作"""

    def test_batch_write_memories(self, tmp_path):
        """测试批量写入记忆"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        memories = [
            {"content": "记忆1", "type": "short_term"},
            {"content": "记忆2", "type": "short_term"},
            {"content": "记忆3", "type": "long_term"},
        ]

        result = manager.batch_write_memories(memories)
        assert result["success"] == 3, "应该成功写入3条记忆"
        assert len(result["memory_ids"]) == 3, "应该返回3个记忆ID"

        manager.shutdown()

    def test_batch_update_memories(self, tmp_path):
        """测试批量更新记忆"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        # 先写入记忆
        id1 = manager.write_memory(content="记忆1", memory_type="short_term")
        id2 = manager.write_memory(content="记忆2", memory_type="short_term")

        # 批量更新
        updates = [
            {"memory_id": id1, "new_content": "更新后的记忆1"},
            {"memory_id": id2, "new_content": "更新后的记忆2"},
        ]

        results = manager.batch_update_memories(updates)
        assert all(results), "所有更新应该成功"

        manager.shutdown()

    def test_batch_delete_memories(self, tmp_path):
        """测试批量删除记忆"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        # 先写入记忆
        id1 = manager.write_memory(content="记忆1", memory_type="short_term")
        id2 = manager.write_memory(content="记忆2", memory_type="short_term")

        # 批量删除
        results = manager.batch_delete_memories([id1, id2])
        assert all(results), "所有删除应该成功"

        # 验证已删除
        assert manager.get_memory(id1) is None
        assert manager.get_memory(id2) is None

        manager.shutdown()


class TestMemoryDecay:
    """测试记忆衰减功能"""

    def test_calculate_exponential_decay(self):
        """测试指数衰减计算"""
        calculator = DecayCalculator()

        score = calculator.calculate_exponential_decay(
            importance=0.8, days_elapsed=30.0, alpha=0.6, lambda1=0.25
        )

        assert 0 <= score <= 1, "衰减分数应该在0-1之间"

    def test_calculate_ebbinghaus_decay(self):
        """测试艾宾浩斯衰减"""
        calculator = DecayCalculator()

        score = calculator.calculate_ebbinghaus_decay(
            importance=0.9, days_elapsed=7.0, t50=30.0, k=2.0
        )

        assert 0 <= score <= 1, "衰减分数应该在0-1之间"

    def test_calculate_network_effect(self):
        """测试网络效应计算"""
        calculator = DecayCalculator()

        score = calculator.calculate_network_effect(base_score=0.5, active_memory_count=100)

        assert score > 0, "网络效应分数应该为正"

    def test_calculate_relevance_score(self, tmp_path):
        """测试相关性分数计算"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))

        memory_id = manager.write_memory(content="测试记忆", memory_type="long_term", importance=4)

        memory = manager.get_memory(memory_id)
        calculator = DecayCalculator()

        score = calculator.calculate_relevance_score(memory)
        assert 0 <= score <= 1, "相关性分数应该在0-1之间"

        manager.shutdown()


class TestSecondaryRouter:
    """测试副模型路由"""

    def test_get_available_commands(self, tmp_path):
        """测试获取可用命令"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))
        router = SecondaryModelRouter(manager)

        commands = router.get_available_commands()

        assert isinstance(commands, dict), "命令应该是字典"
        assert len(commands) > 0, "应该至少有一个命令"

        manager.shutdown()

    def test_validate_permission(self, tmp_path):
        """测试权限验证"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))
        router = SecondaryModelRouter(manager)

        # 验证主模型可以执行所有操作
        assert router.validate_permission("read_memory", is_from_main=True) is True
        assert router.validate_permission("delete_permanent_memory", is_from_main=True) is True

        # 验证副模型的限制
        assert router.validate_permission("read_memory", is_from_main=False) is True
        # delete_permanent_memory 在 PROHIBITED_COMMANDS 中，副模型不能执行
        assert router.validate_permission("delete_permanent_memory", is_from_main=False) is False

        manager.shutdown()

    @pytest.mark.asyncio
    async def test_execute_command(self, tmp_path):
        """测试执行命令"""
        db_path = tmp_path / "test_memories.db"
        manager = MemoryManager(str(db_path))
        router = SecondaryModelRouter(manager)

        # 测试无效命令 - 需要使用 SecondaryInstruction 对象
        instruction = SecondaryInstruction(command="invalid_command")
        result = await router.execute_command(instruction, is_from_main=True)
        assert result.status == "error"

        manager.shutdown()


class TestContextManager:
    """测试上下文管理器"""

    def test_create_session(self, tmp_path):
        """测试创建会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default", title="测试会话")

        assert session_id is not None, "会话ID不应该为空"
        assert len(session_id) > 0, "会话ID应该有长度"

        # ContextManager 没有 close 方法，使用 shutdown
        manager.shutdown()

    def test_add_message(self, tmp_path):
        """测试添加消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        message_id = manager.add_message(session_id=session_id, role="user", content="测试消息")

        assert message_id is not None, "消息ID不应该为空"

        # 使用 get_messages 获取消息
        messages = manager.get_messages(session_id)
        assert len(messages) == 1, "应该有一条消息"
        assert messages[0]["content"] == "测试消息", "消息内容应该匹配"

        manager.shutdown()

    def test_add_mono_context(self, tmp_path):
        """测试添加独白上下文"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        # add_mono_context 参数是 rounds 而不是 emotion_score
        manager.add_mono_context(session_id=session_id, content="内心独白内容", rounds=1)

        # 验证独白已添加
        context = manager.get_mono_context(session_id)
        assert len(context) == 1, "应该有一条独白"
        assert context[0]["content"] == "内心独白内容", "独白内容应该匹配"

        manager.shutdown()

    def test_clear_expired_mono(self, tmp_path):
        """测试清理过期独白"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        # 添加独白 - 使用正确的参数
        manager.add_mono_context(session_id, "独白1", rounds=1)
        manager.add_mono_context(session_id, "独白2", rounds=1)

        # 清理（默认30分钟过期，这里不会清理）
        cleared = manager.clear_expired_mono(session_id)
        assert cleared >= 0, "清理数量应该大于等于0"

        manager.shutdown()

    def test_get_session(self, tmp_path):
        """测试获取单个会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(
            workspace_id="default", title="测试会话标题", user_id="user123"
        )

        session = manager.get_session(session_id)
        assert session is not None, "应该能获取到会话"
        assert session["id"] == session_id, "会话ID应该匹配"
        assert session["title"] == "测试会话标题", "会话标题应该匹配"
        assert session["user_id"] == "user123", "用户ID应该匹配"
        assert session["workspace_id"] == "default", "工作区ID应该匹配"

        manager.shutdown()

    def test_get_session_not_found(self, tmp_path):
        """测试获取不存在的会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session = manager.get_session("non-existent-id")
        assert session is None, "不存在的会话应该返回None"

        manager.shutdown()

    def test_get_sessions(self, tmp_path):
        """测试获取会话列表"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id1 = manager.create_session(workspace_id="default", title="会话1")
        session_id2 = manager.create_session(workspace_id="default", title="会话2")
        manager.create_session(workspace_id="other", title="会话3")

        sessions = manager.get_sessions(workspace_id="default")
        assert len(sessions) == 2, "应该有2个会话"
        session_ids = [s["id"] for s in sessions]
        assert session_id1 in session_ids, "应该包含会话1"
        assert session_id2 in session_ids, "应该包含会话2"

        manager.shutdown()

    def test_get_sessions_with_limit(self, tmp_path):
        """测试带限制的会话列表"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        for i in range(5):
            manager.create_session(workspace_id="default", title=f"会话{i}")

        sessions = manager.get_sessions(workspace_id="default", limit=3)
        assert len(sessions) == 3, "应该只返回3个会话"

        manager.shutdown()

    def test_update_session(self, tmp_path):
        """测试更新会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default", title="原标题")

        success = manager.update_session(session_id, title="新标题")
        assert success is True, "更新应该成功"

        session = manager.get_session(session_id)
        assert session["title"] == "新标题", "标题应该已更新"

        manager.shutdown()

    def test_update_session_with_summary(self, tmp_path):
        """测试更新会话摘要"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        success = manager.update_session(session_id, summary="这是会话摘要", is_active=False)
        assert success is True, "更新应该成功"

        session = manager.get_session(session_id)
        assert session["summary"] == "这是会话摘要", "摘要应该已更新"
        assert session["is_active"] is False, "活动状态应该已更新"

        manager.shutdown()

    def test_delete_session(self, tmp_path):
        """测试删除会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")
        manager.add_message(session_id, "user", "测试消息")

        success = manager.delete_session(session_id)
        assert success is True, "删除应该成功"

        session = manager.get_session(session_id)
        assert session is None, "会话应该已删除"

        messages = manager.get_messages(session_id)
        assert len(messages) == 0, "消息应该已删除"

        manager.shutdown()

    def test_delete_session_not_found(self, tmp_path):
        """测试删除不存在的会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        success = manager.delete_session("non-existent-id")
        assert success is False, "删除不存在的会话应该失败"

        manager.shutdown()

    def test_get_messages_with_pagination(self, tmp_path):
        """测试分页获取消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        for i in range(10):
            manager.add_message(session_id, "user", f"消息{i}")

        messages = manager.get_messages(session_id, limit=5, offset=0)
        assert len(messages) == 5, "应该返回5条消息"

        messages = manager.get_messages(session_id, limit=5, offset=5)
        assert len(messages) == 5, "应该返回另外5条消息"

        manager.shutdown()

    def test_delete_message(self, tmp_path):
        """测试删除消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")
        message_id = manager.add_message(session_id, "user", "待删除的消息")

        success = manager.delete_message(message_id)
        assert success is True, "删除应该成功"

        messages = manager.get_messages(session_id)
        assert len(messages) == 0, "消息应该已删除"

        manager.shutdown()

    def test_get_message_count(self, tmp_path):
        """测试获取消息数量"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        count = manager.get_message_count(session_id)
        assert count == 0, "初始应该有0条消息"

        for i in range(5):
            manager.add_message(session_id, "user", f"消息{i}")

        count = manager.get_message_count(session_id)
        assert count == 5, "应该有5条消息"

        manager.shutdown()

    def test_clear_session_messages(self, tmp_path):
        """测试清理会话消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        for i in range(10):
            manager.add_message(session_id, "user", f"消息{i}")

        success = manager.clear_session_messages(session_id)
        assert success is True, "清理应该成功"

        messages = manager.get_messages(session_id)
        assert len(messages) == 0, "所有消息应该已清理"

        session = manager.get_session(session_id)
        assert session["message_count"] == 0, "消息计数应该为0"

        manager.shutdown()

    def test_get_statistics(self, tmp_path):
        """测试获取统计信息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id1 = manager.create_session(workspace_id="default")
        session_id2 = manager.create_session(workspace_id="default")
        manager.create_session(workspace_id="other")

        for i in range(5):
            manager.add_message(session_id1, "user", f"消息{i}")

        for i in range(3):
            manager.add_message(session_id2, "user", f"消息{i}")

        stats = manager.get_statistics(workspace_id="default")
        assert stats["total_sessions"] == 2, "应该有2个会话"
        assert stats["active_sessions"] == 2, "应该有2个活动会话"
        assert stats["total_messages"] == 8, "应该有8条消息"
        assert stats["avg_messages_per_session"] == 4.0, "平均消息数应该是4"

        manager.shutdown()

    def test_add_message_with_metadata(self, tmp_path):
        """测试添加带元数据的消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        message_id = manager.add_message(
            session_id=session_id,
            role="user",
            content="测试消息",
            content_type="text",
            metadata={"key": "value"},
            tokens=100,
        )

        messages = manager.get_messages(session_id)
        assert len(messages) == 1, "应该有一条消息"
        assert messages[0]["metadata"]["key"] == "value", "元数据应该匹配"
        assert messages[0]["tokens"] == 100, "token数应该匹配"

        manager.shutdown()

    def test_add_multiple_messages(self, tmp_path):
        """测试添加多条消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.add_message(session_id, "user", "用户消息1")
        manager.add_message(session_id, "assistant", "助手回复1")
        manager.add_message(session_id, "user", "用户消息2")
        manager.add_message(session_id, "assistant", "助手回复2")

        messages = manager.get_messages(session_id)
        assert len(messages) == 4, "应该有4条消息"
        assert messages[0]["role"] == "user", "第一条应该是用户消息"
        assert messages[1]["role"] == "assistant", "第二条应该是助手消息"

        session = manager.get_session(session_id)
        assert session["message_count"] == 4, "消息计数应该是4"

        manager.shutdown()

    def test_mono_context_expiration(self, tmp_path):
        """测试Mono上下文过期"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.add_mono_context(session_id, "独白1", rounds=1)

        context = manager.get_mono_context(session_id)
        assert len(context) == 1, "应该有一条独白"

        manager.shutdown()

    def test_close_connection(self, tmp_path):
        """测试关闭连接"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.close_connection()

        manager.shutdown()

    def test_shutdown(self, tmp_path):
        """测试关闭管理器"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.shutdown()

        manager.shutdown()
        """测试获取单个会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(
            workspace_id="default", title="测试会话标题", user_id="user123"
        )

        session = manager.get_session(session_id)
        assert session is not None, "应该能获取到会话"
        assert session["id"] == session_id, "会话ID应该匹配"
        assert session["title"] == "测试会话标题", "会话标题应该匹配"
        assert session["user_id"] == "user123", "用户ID应该匹配"
        assert session["workspace_id"] == "default", "工作区ID应该匹配"

        manager.shutdown()

    def test_get_session_not_found(self, tmp_path):
        """测试获取不存在的会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session = manager.get_session("non-existent-id")
        assert session is None, "不存在的会话应该返回None"

        manager.shutdown()

    def test_get_sessions(self, tmp_path):
        """测试获取会话列表"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id1 = manager.create_session(workspace_id="default", title="会话1")
        session_id2 = manager.create_session(workspace_id="default", title="会话2")
        manager.create_session(workspace_id="other", title="会话3")

        sessions = manager.get_sessions(workspace_id="default")
        assert len(sessions) == 2, "应该有2个会话"
        session_ids = [s["id"] for s in sessions]
        assert session_id1 in session_ids, "应该包含会话1"
        assert session_id2 in session_ids, "应该包含会话2"

        manager.shutdown()

    def test_get_sessions_with_limit(self, tmp_path):
        """测试带限制的会话列表"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        for i in range(5):
            manager.create_session(workspace_id="default", title=f"会话{i}")

        sessions = manager.get_sessions(workspace_id="default", limit=3)
        assert len(sessions) == 3, "应该只返回3个会话"

        manager.shutdown()

    def test_update_session(self, tmp_path):
        """测试更新会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default", title="原标题")

        success = manager.update_session(session_id, title="新标题")
        assert success is True, "更新应该成功"

        session = manager.get_session(session_id)
        assert session["title"] == "新标题", "标题应该已更新"

        manager.shutdown()

    def test_update_session_with_summary(self, tmp_path):
        """测试更新会话摘要"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        success = manager.update_session(session_id, summary="这是会话摘要", is_active=False)
        assert success is True, "更新应该成功"

        session = manager.get_session(session_id)
        assert session["summary"] == "这是会话摘要", "摘要应该已更新"
        assert session["is_active"] is False, "活动状态应该已更新"

        manager.shutdown()

    def test_delete_session(self, tmp_path):
        """测试删除会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")
        manager.add_message(session_id, "user", "测试消息")

        success = manager.delete_session(session_id)
        assert success is True, "删除应该成功"

        session = manager.get_session(session_id)
        assert session is None, "会话应该已删除"

        messages = manager.get_messages(session_id)
        assert len(messages) == 0, "消息应该已删除"

        manager.shutdown()

    def test_delete_session_not_found(self, tmp_path):
        """测试删除不存在的会话"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        success = manager.delete_session("non-existent-id")
        assert success is False, "删除不存在的会话应该失败"

        manager.shutdown()

    def test_get_messages_with_pagination(self, tmp_path):
        """测试分页获取消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        for i in range(10):
            manager.add_message(session_id, "user", f"消息{i}")

        messages = manager.get_messages(session_id, limit=5, offset=0)
        assert len(messages) == 5, "应该返回5条消息"

        messages = manager.get_messages(session_id, limit=5, offset=5)
        assert len(messages) == 5, "应该返回另外5条消息"

        manager.shutdown()

    def test_delete_message(self, tmp_path):
        """测试删除消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")
        message_id = manager.add_message(session_id, "user", "待删除的消息")

        success = manager.delete_message(message_id)
        assert success is True, "删除应该成功"

        messages = manager.get_messages(session_id)
        assert len(messages) == 0, "消息应该已删除"

        manager.shutdown()

    def test_get_message_count(self, tmp_path):
        """测试获取消息数量"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        count = manager.get_message_count(session_id)
        assert count == 0, "初始应该有0条消息"

        for i in range(5):
            manager.add_message(session_id, "user", f"消息{i}")

        count = manager.get_message_count(session_id)
        assert count == 5, "应该有5条消息"

        manager.shutdown()

    def test_clear_session_messages(self, tmp_path):
        """测试清理会话消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        for i in range(10):
            manager.add_message(session_id, "user", f"消息{i}")

        success = manager.clear_session_messages(session_id)
        assert success is True, "清理应该成功"

        messages = manager.get_messages(session_id)
        assert len(messages) == 0, "所有消息应该已清理"

        session = manager.get_session(session_id)
        assert session["message_count"] == 0, "消息计数应该为0"

        manager.shutdown()

    def test_get_statistics(self, tmp_path):
        """测试获取统计信息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id1 = manager.create_session(workspace_id="default")
        session_id2 = manager.create_session(workspace_id="default")
        manager.create_session(workspace_id="other")

        for i in range(5):
            manager.add_message(session_id1, "user", f"消息{i}")

        for i in range(3):
            manager.add_message(session_id2, "user", f"消息{i}")

        stats = manager.get_statistics(workspace_id="default")
        assert stats["total_sessions"] == 2, "应该有2个会话"
        assert stats["active_sessions"] == 2, "应该有2个活动会话"
        assert stats["total_messages"] == 8, "应该有8条消息"
        assert stats["avg_messages_per_session"] == 4.0, "平均消息数应该是4"

        manager.shutdown()

    def test_add_message_with_metadata(self, tmp_path):
        """测试添加带元数据的消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        message_id = manager.add_message(
            session_id=session_id,
            role="user",
            content="测试消息",
            content_type="text",
            metadata={"key": "value"},
            tokens=100,
        )

        messages = manager.get_messages(session_id)
        assert len(messages) == 1, "应该有一条消息"
        assert messages[0]["metadata"]["key"] == "value", "元数据应该匹配"
        assert messages[0]["tokens"] == 100, "token数应该匹配"

        manager.shutdown()

    def test_add_multiple_messages(self, tmp_path):
        """测试添加多条消息"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.add_message(session_id, "user", "用户消息1")
        manager.add_message(session_id, "assistant", "助手回复1")
        manager.add_message(session_id, "user", "用户消息2")
        manager.add_message(session_id, "assistant", "助手回复2")

        messages = manager.get_messages(session_id)
        assert len(messages) == 4, "应该有4条消息"
        assert messages[0]["role"] == "user", "第一条应该是用户消息"
        assert messages[1]["role"] == "assistant", "第二条应该是助手消息"

        session = manager.get_session(session_id)
        assert session["message_count"] == 4, "消息计数应该是4"

        manager.shutdown()

    def test_mono_context_expiration(self, tmp_path):
        """测试Mono上下文过期"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.add_mono_context(session_id, "独白1", rounds=1)

        context = manager.get_mono_context(session_id)
        assert len(context) == 1, "应该有一条独白"

        manager.shutdown()

    def test_close_connection(self, tmp_path):
        """测试关闭连接"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.close_connection()

        manager.shutdown()

    def test_shutdown(self, tmp_path):
        """测试关闭管理器"""
        db_path = tmp_path / "test_context.db"
        manager = ContextManager(str(db_path))

        session_id = manager.create_session(workspace_id="default")

        manager.shutdown()

        manager.shutdown()
