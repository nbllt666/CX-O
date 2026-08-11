"""
上下文管理器 - 管理对话上下文
"""
from typing import List, Dict

from server.config import Settings


class ContextManager:

    def __init__(self, max_history: int = None):
        if max_history is None:
            max_history = Settings().config.limits.context.max_history
        self.max_history = max_history
        self.contexts: Dict[str, List[Dict]] = {}

    def add_message(self, session_id: str, message: Dict[str, str]):
        if session_id not in self.contexts:
            self.contexts[session_id] = []

        self.contexts[session_id].append(message)

        if len(self.contexts[session_id]) > self.max_history:
            self.contexts[session_id] = self.contexts[session_id][-self.max_history:]

    def add_danmaku_message(self, session_id: str, danmaku_data: Dict) -> Dict[str, str]:
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
        return self.contexts.get(session_id, [])

    def clear_context(self, session_id: str):
        if session_id in self.contexts:
            del self.contexts[session_id]


_context_manager = ContextManager()


def get_context_manager() -> ContextManager:
    return _context_manager
