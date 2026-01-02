#!/usr/bin/env python3
"""
对话上下文管理器

功能：
- 对话上下文持久化（JSON文件）
- 会话管理
- Mono上下文管理
- 内存缓存加速
"""

from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import json
import logging
import os

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """消息数据类"""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    audio_path: Optional[str] = None
    audio_data: Optional[str] = None  # base64编码的音频数据
    metadata: Optional[Dict] = None


@dataclass
class MonoContextItem:
    """Mono上下文项"""
    content: str
    expires_at: str  # ISO格式过期时间
    rounds: int = 1


class ContextManager:
    """对话上下文管理器"""
    
    def __init__(
        self,
        context_dir: str = "data/contexts",
        max_messages: int = 40,  # 默认保留最近20轮 = 40条消息
        cache_ttl: int = 3600,  # 缓存1小时
        max_cache_size: int = 100  # 最多缓存100个会话
    ):
        """
        初始化上下文管理器
        
        Args:
            context_dir: 上下文文件存储目录
            max_messages: 最大消息数量
            cache_ttl: 缓存TTL（秒）
            max_cache_size: 最大缓存会话数
        """
        self.context_dir = Path(context_dir)
        self.sessions_dir = self.context_dir / "sessions"
        self.max_messages = max_messages
        self.cache_ttl = cache_ttl
        self.max_cache_size = max_cache_size
        
        # 创建目录
        self.context_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存（加速访问）
        self._memory_cache: Dict[str, Dict] = {}
        self._cache_order: List[str] = []  # 用于LRU淘汰
    
    def save_context(
        self,
        session_id: str,
        messages: List[Dict],
        metadata: Dict = None,
        mono_context: List[Dict] = None
    ):
        """
        保存对话上下文到文件
        
        Args:
            session_id: 会话ID
            messages: 消息列表
            metadata: 元数据（可选）
            mono_context: Mono上下文（可选）
        """
        context_file = self.sessions_dir / f"{session_id}.json"
        
        context = {
            "session_id": session_id,
            "created_at": self._get_or_create_created_at(session_id),
            "last_active": datetime.now().isoformat(),
            "messages": messages,
            "mono_context": mono_context or [],
            "memory_references": [],
            "metadata": metadata or {}
        }
        
        try:
            # 写入文件
            with open(context_file, 'w', encoding='utf-8') as f:
                json.dump(context, f, ensure_ascii=False, indent=2)
            
            # 更新内存缓存
            self._update_cache(session_id, context)
            
            logger.debug(f"上下文已保存: session_id={session_id}, messages={len(messages)}")
        
        except Exception as e:
            logger.error(f"保存上下文失败: {e}")
            raise
    
    def load_context(self, session_id: str) -> List[Dict]:
        """
        从文件加载对话上下文
        
        Args:
            session_id: 会话ID
        
        Returns:
            消息列表
        """
        # 先检查内存缓存
        if session_id in self._memory_cache:
            cached = self._memory_cache[session_id]
            if self._is_cache_valid(cached):
                return cached.get("messages", [])
        
        # 从文件加载
        context_file = self.sessions_dir / f"{session_id}.json"
        
        if not context_file.exists():
            logger.debug(f"上下文文件不存在: {context_file}")
            return []
        
        try:
            with open(context_file, 'r', encoding='utf-8') as f:
                context = json.load(f)
            
            # 更新内存缓存
            self._update_cache(session_id, context)
            
            return context.get("messages", [])
        
        except Exception as e:
            logger.error(f"加载上下文失败: {e}")
            return []
    
    def append_message(self, session_id: str, message: Dict):
        """
        追加单条消息到上下文
        
        Args:
            session_id: 会话ID
            message: 消息内容
        """
        messages = self.load_context(session_id)
        messages.append(message)
        
        # 限制上下文长度
        if len(messages) > self.max_messages:
            messages = messages[-self.max_messages:]
        
        # 保存
        self.save_context(session_id, messages)
    
    def get_recent_messages(
        self,
        session_id: str,
        count: int = 10
    ) -> List[Dict]:
        """
        获取最近的N条消息
        
        Args:
            session_id: 会话ID
            count: 返回消息数量
        
        Returns:
            最近的消息列表
        """
        messages = self.load_context(session_id)
        return messages[-count:]
    
    def clear_context(self, session_id: str):
        """
        清空会话上下文（删除文件）
        
        Args:
            session_id: 会话ID
        """
        context_file = self.sessions_dir / f"{session_id}.json"
        
        if context_file.exists():
            context_file.unlink()
            # 清除内存缓存
            self._memory_cache.pop(session_id, None)
            if session_id in self._cache_order:
                self._cache_order.remove(session_id)
            
            logger.debug(f"上下文已清除: session_id={session_id}")
    
    def list_sessions(self, limit: int = 50) -> List[Dict]:
        """
        列出所有会话
        
        Args:
            limit: 返回数量限制
        
        Returns:
            会话信息列表
        """
        sessions = []
        
        for context_file in self.sessions_dir.glob("*.json"):
            try:
                with open(context_file, 'r', encoding='utf-8') as f:
                    context = json.load(f)
                
                sessions.append({
                    "session_id": context["session_id"],
                    "created_at": context["created_at"],
                    "last_active": context["last_active"],
                    "message_count": len(context.get("messages", [])),
                    "metadata": context.get("metadata", {})
                })
            
            except Exception as e:
                logger.error(f"读取会话信息失败: {context_file}, error: {e}")
        
        # 按最后活跃时间排序
        sessions.sort(key=lambda x: x["last_active"], reverse=True)
        
        return sessions[:limit]
    
    # ========== Mono上下文管理 ==========
    
    def add_mono_context(
        self,
        session_id: str,
        content: str,
        rounds: int = 1
    ):
        """
        添加Mono上下文（保持信息在上下文中）
        
        Args:
            session_id: 会话ID
            content: 要保持的信息
            rounds: 保持轮数（默认1轮）
        """
        messages = self.load_context(session_id)
        mono_context = self._load_mono_context(session_id)
        
        # 计算过期时间
        expires_at = datetime.now() + timedelta(rounds=rounds)
        
        mono_context.append({
            "content": content,
            "expires_at": expires_at.isoformat(),
            "rounds": rounds
        })
        
        # 保存
        self.save_context(session_id, messages, mono_context=mono_context)
        
        logger.debug(f"Mono上下文已添加: session_id={session_id}, content={content[:50]}...")
    
    def get_mono_context(self, session_id: str) -> List[str]:
        """
        获取有效的Mono上下文
        
        Args:
            session_id: 会话ID
        
        Returns:
            有效的Mono内容列表
        """
        mono_context = self._load_mono_context(session_id)
        now = datetime.now()
        
        valid_contexts = []
        for item in mono_context:
            try:
                expires_at = datetime.fromisoformat(item["expires_at"])
                if expires_at > now:
                    valid_contexts.append(item["content"])
            except:
                pass
        
        return valid_contexts
    
    def clear_expired_mono(self, session_id: str):
        """
        清理过期的Mono上下文
        """
        messages = self.load_context(session_id)
        mono_context = self._load_mono_context(session_id)
        
        now = datetime.now()
        valid_context = []
        
        for item in mono_context:
            try:
                expires_at = datetime.fromisoformat(item["expires_at"])
                if expires_at > now:
                    valid_context.append(item)
            except:
                pass
        
        if len(valid_context) != len(mono_context):
            self.save_context(session_id, messages, mono_context=valid_context)
            logger.debug(f"已清理过期Mono上下文: session_id={session_id}")
    
    # ========== 辅助方法 ==========
    
    def _load_mono_context(self, session_id: str) -> List[Dict]:
        """加载Mono上下文"""
        context_file = self.sessions_dir / f"{session_id}.json"
        
        if not context_file.exists():
            return []
        
        try:
            with open(context_file, 'r', encoding='utf-8') as f:
                context = json.load(f)
            return context.get("mono_context", [])
        except:
            return []
    
    def _update_cache(self, session_id: str, context: Dict):
        """更新内存缓存（LRU策略）"""
        self._memory_cache[session_id] = {
            "data": context,
            "timestamp": datetime.now()
        }
        
        # 更新访问顺序
        if session_id in self._cache_order:
            self._cache_order.remove(session_id)
        self._cache_order.append(session_id)
        
        # 限制缓存大小（LRU淘汰）
        while len(self._memory_cache) > self.max_cache_size:
            if self._cache_order:
                oldest_key = self._cache_order.pop(0)
                self._memory_cache.pop(oldest_key, None)
    
    def _is_cache_valid(self, cached: Dict) -> bool:
        """检查缓存是否有效"""
        if not cached:
            return False
        
        timestamp = cached.get("timestamp")
        if not timestamp:
            return False
        
        try:
            cached_time = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else timestamp
            elapsed = (datetime.now() - cached_time).total_seconds()
            return elapsed < self.cache_ttl
        except:
            return False
    
    def _get_or_create_created_at(self, session_id: str) -> str:
        """获取或创建会话创建时间"""
        context_file = self.sessions_dir / f"{session_id}.json"
        
        if context_file.exists():
            try:
                with open(context_file, 'r', encoding='utf-8') as f:
                    context = json.load(f)
                return context.get("created_at", datetime.now().isoformat())
            except:
                pass
        
        return datetime.now().isoformat()
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        sessions = self.list_sessions(limit=10000)
        
        total_messages = sum(s["message_count"] for s in sessions)
        
        return {
            "session_count": len(sessions),
            "total_messages": total_messages,
            "active_connections": len(self._memory_cache),
            "cache_size": len(self._memory_cache)
        }
