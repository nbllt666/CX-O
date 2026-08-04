"""
Agent上下文管理器
负责记忆管理Agent的上下文持久化存储
"""

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class AgentContextData:
    """Agent上下文数据结构"""

    agent_id: str
    session_id: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    memory_state: Optional[Dict[str, Any]] = None
    last_active: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AgentContextManager:
    """Agent上下文管理器 - 负责记忆管理Agent的上下文持久化

    功能：
    1. 保存和加载Agent的上下文数据
    2. 管理Agent的消息历史
    3. 支持上下文压缩和摘要
    4. 跨会话保持Agent状态

    使用模块级单例，通过 get_agent_context_manager() 获取实例。

    Attributes:
        storage_dir: JSON文件存储目录
        _lock: 线程锁，保证线程安全
        _cache: 内存缓存
    """

    def __init__(self, storage_dir: str = "data/agent_contexts") -> None:
        """初始化Agent上下文管理器

        Args:
            storage_dir: JSON文件存储目录
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: Dict[str, AgentContextData] = {}

        logger.info(f"Agent上下文管理器初始化完成: storage_dir={storage_dir}")

    def _get_file_path(self, agent_id: str) -> Path:
        """获取Agent对应的JSON文件路径

        Args:
            agent_id: Agent唯一标识

        Returns:
            JSON文件路径
        """
        return self.storage_dir / f"{agent_id}.json"

    def _load_from_file(self, agent_id: str) -> Optional[AgentContextData]:
        """从文件加载上下文数据

        Args:
            agent_id: Agent唯一标识

        Returns:
            AgentContextData 或 None
        """
        file_path = self._get_file_path(agent_id)
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AgentContextData(
                agent_id=data["agent_id"],
                session_id=data.get("session_id"),
                messages=data.get("messages", []),
                memory_state=data.get("memory_state"),
                last_active=data.get("last_active"),
                created_at=data.get("created_at"),
                updated_at=data.get("updated_at"),
            )
        except Exception as e:
            logger.error(f"从文件加载Agent上下文失败: {e}")
            return None

    def _save_to_file(self, context_data: AgentContextData):
        """将上下文数据保存到文件

        Args:
            context_data: Agent上下文数据
        """
        file_path = self._get_file_path(context_data.agent_id)
        try:
            data = {
                "agent_id": context_data.agent_id,
                "session_id": context_data.session_id,
                "messages": context_data.messages,
                "memory_state": context_data.memory_state,
                "last_active": context_data.last_active,
                "created_at": context_data.created_at,
                "updated_at": context_data.updated_at,
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存Agent上下文到文件失败: {e}")
            raise

    def _get_or_load(self, agent_id: str) -> AgentContextData:
        """从缓存获取或从文件加载上下文数据

        Args:
            agent_id: Agent唯一标识

        Returns:
            AgentContextData
        """
        if agent_id in self._cache:
            return self._cache[agent_id]
        context_data = self._load_from_file(agent_id)
        if context_data is not None:
            self._cache[agent_id] = context_data
            return context_data
        # 返回空的上下文数据（不缓存空数据）
        return AgentContextData(agent_id=agent_id)

    def save_context(
        self,
        agent_id: str,
        messages: List[Dict[str, Any]],
        memory_state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ):
        """保存Agent上下文

        Args:
            agent_id: Agent唯一标识
            messages: 消息列表，每个消息包含role和content
            memory_state: 记忆管理器状态（可选）
            session_id: 关联的会话ID（可选）
        """
        try:
            with self._lock:
                now = datetime.now().isoformat()
                context_data = self._get_or_load(agent_id)

                context_data.messages = messages
                context_data.memory_state = memory_state
                context_data.session_id = session_id
                context_data.last_active = now
                context_data.updated_at = now
                if context_data.created_at is None:
                    context_data.created_at = now

                self._cache[agent_id] = context_data
                self._save_to_file(context_data)

            logger.debug(f"Agent '{agent_id}' 上下文已保存")
        except Exception as e:
            logger.error(f"保存Agent上下文失败: {e}")
            raise

    def load_context(self, agent_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """加载Agent上下文

        Args:
            agent_id: Agent唯一标识
            limit: 最大返回消息数量

        Returns:
            消息列表
        """
        try:
            with self._lock:
                context_data = self._get_or_load(agent_id)

            # limit=0 特殊处理：messages[-0:] 等价于 messages[0:]（返回全部），
            # 需显式返回空列表
            if limit == 0:
                return []
            messages = context_data.messages
            if len(messages) > limit:
                messages = messages[-limit:]
            # 只返回 role 和 content
            return [{"role": m.get("role"), "content": m.get("content")} for m in messages]
        except Exception as e:
            logger.error(f"加载Agent上下文失败: {e}")
            return []

    def append_message(
        self, agent_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ):
        """追加消息到上下文历史

        Args:
            agent_id: Agent唯一标识
            role: 消息角色 (system/user/assistant/tool)
            content: 消息内容
            metadata: 额外元数据（可选）
        """
        try:
            with self._lock:
                now = datetime.now().isoformat()
                context_data = self._get_or_load(agent_id)

                message = {
                    "role": role,
                    "content": content,
                    "metadata": metadata,
                    "created_at": now,
                }
                context_data.messages.append(message)
                context_data.last_active = now
                context_data.updated_at = now
                if context_data.created_at is None:
                    context_data.created_at = now

                self._cache[agent_id] = context_data
                self._save_to_file(context_data)

            logger.debug(f"Agent '{agent_id}' 消息已追加: role={role}")
        except Exception as e:
            logger.error(f"追加Agent消息失败: {e}")
            raise

    def get_message_history(self, agent_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """获取消息历史

        Args:
            agent_id: Agent唯一标识
            limit: 最大返回消息数量

        Returns:
            消息历史列表
        """
        try:
            with self._lock:
                context_data = self._get_or_load(agent_id)

            messages = context_data.messages
            if limit == 0:
                messages = []
            elif len(messages) > limit:
                messages = messages[-limit:]

            # 返回完整消息（含 role, content, metadata, created_at）
            return [
                {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "metadata": m.get("metadata"),
                    "created_at": m.get("created_at"),
                }
                for m in messages
            ]
        except Exception as e:
            logger.error(f"获取Agent消息历史失败: {e}")
            return []

    def clear_context(self, agent_id: str):
        """清空Agent上下文

        Args:
            agent_id: Agent唯一标识
        """
        try:
            with self._lock:
                # 清空缓存
                self._cache.pop(agent_id, None)
                # 删除文件
                file_path = self._get_file_path(agent_id)
                if file_path.exists():
                    file_path.unlink()

            logger.info(f"Agent '{agent_id}' 上下文已清空")
        except Exception as e:
            logger.error(f"清空Agent上下文失败: {e}")
            raise

    def get_context_summary(self, agent_id: str) -> Dict[str, Any]:
        """获取上下文摘要

        Args:
            agent_id: Agent唯一标识

        Returns:
            上下文摘要信息
        """
        try:
            with self._lock:
                context_data = self._get_or_load(agent_id)

            role_counts: Dict[str, int] = {}
            for msg in context_data.messages:
                role = msg.get("role", "unknown")
                role_counts[role] = role_counts.get(role, 0) + 1

            has_context = (
                context_data.created_at is not None or len(context_data.messages) > 0
            )

            return {
                "agent_id": agent_id,
                "has_context": has_context,
                "session_id": context_data.session_id,
                "last_active": context_data.last_active,
                "created_at": context_data.created_at,
                "updated_at": context_data.updated_at,
                "total_messages": len(context_data.messages),
                "role_counts": role_counts,
            }
        except Exception as e:
            logger.error(f"获取Agent上下文摘要失败: {e}")
            return {"agent_id": agent_id, "error": str(e)}

    def update_last_active(self, agent_id: str):
        """更新最后活跃时间

        Args:
            agent_id: Agent唯一标识
        """
        try:
            with self._lock:
                now = datetime.now().isoformat()
                context_data = self._get_or_load(agent_id)

                context_data.last_active = now
                context_data.updated_at = now
                if context_data.created_at is None:
                    context_data.created_at = now

                self._cache[agent_id] = context_data
                self._save_to_file(context_data)

        except Exception as e:
            logger.error(f"更新Agent最后活跃时间失败: {e}")

    def cleanup_old_messages(self, agent_id: str, keep_count: int = 1000):
        """清理旧消息，只保留最近N条

        Args:
            agent_id: Agent唯一标识
            keep_count: 保留的消息数量
        """
        try:
            with self._lock:
                context_data = self._get_or_load(agent_id)

                # keep_count=0 特殊处理：messages[-0:] 等价于 messages[0:]（保留全部），
                # 需显式清空全部消息
                if keep_count == 0:
                    if context_data.messages:
                        context_data.messages = []
                        context_data.updated_at = datetime.now().isoformat()
                        self._cache[agent_id] = context_data
                        self._save_to_file(context_data)
                        logger.info(
                            f"Agent '{agent_id}' 已清空全部消息（keep_count=0）"
                        )
                elif len(context_data.messages) > keep_count:
                    context_data.messages = context_data.messages[-keep_count:]
                    context_data.updated_at = datetime.now().isoformat()

                    self._cache[agent_id] = context_data
                    self._save_to_file(context_data)

                    logger.info(
                        f"Agent '{agent_id}' 已清理旧消息，保留最近 {keep_count} 条"
                    )
        except Exception as e:
            logger.error(f"清理Agent旧消息失败: {e}")


# 模块级单例
_instance: Optional[AgentContextManager] = None
_instance_lock = threading.Lock()


def get_agent_context_manager() -> AgentContextManager:
    """获取AgentContextManager单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AgentContextManager()
    return _instance
_instance_lock = threading.Lock()


def get_agent_context_manager() -> AgentContextManager:
    """获取AgentContextManager单例"""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AgentContextManager()
    return _instance
