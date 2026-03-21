"""
上下文管理器 - 管理对话上下文
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ContextManager:
    """管理对话上下文"""
    
    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.contexts: Dict[str, List[Dict]] = {}
        self.system_prompts: Dict[str, str] = {}
    
    def add_message(self, session_id: str, message: Dict[str, str]):
        """添加消息到上下文"""
        if session_id not in self.contexts:
            self.contexts[session_id] = []
        
        self.contexts[session_id].append(message)
        
        # 限制历史长度
        if len(self.contexts[session_id]) > self.max_history:
            self.contexts[session_id] = self.contexts[session_id][-self.max_history:]
    
    def add_danmaku_message(self, session_id: str, danmaku_data: Dict) -> Dict[str, str]:
        """添加弹幕消息到上下文，返回格式化的消息"""
        user = danmaku_data.get("user", {})
        uid = user.get("uid", "")
        username = user.get("username", "")
        content = danmaku_data.get("content", "")
        
        message = {
            "role": f"直播间消息 userid:{uid} username:{username}",
            "content": content
        }
        
        self.add_message(session_id, message)
        return message
    
    def get_context(self, session_id: str) -> List[Dict]:
        """获取上下文"""
        return self.contexts.get(session_id, [])
    
    def clear_context(self, session_id: str):
        """清空上下文"""
        if session_id in self.contexts:
            del self.contexts[session_id]
    
    def set_system_prompt(self, session_id: str, prompt: str):
        """设置会话的系统提示词"""
        self.system_prompts[session_id] = prompt
        logger.debug(f"Set system prompt for session {session_id}: {len(prompt)} chars")
    
    def get_system_prompt(self, session_id: str) -> str:
        """获取会话的系统提示词"""
        return self.system_prompts.get(session_id, "")
    
    def get_context_with_system_prompt(self, session_id: str) -> List[Dict]:
        """获取包含系统提示词的完整上下文"""
        messages = []
        system_prompt = self.get_system_prompt(session_id)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(self.get_context(session_id))
        return messages
    
    def get_context_str(self, session_id: str) -> str:
        """获取格式化的上下文字符串"""
        messages = self.get_context(session_id)
        if not messages:
            return ""
        
        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")
        
        return "\n".join(parts)


# 全局实例
_context_manager = ContextManager()


def get_context_manager() -> ContextManager:
    return _context_manager
