"""
上下文管理器 - 管理对话上下文
"""
import logging
from typing import List, Dict, Any, Optional

from server.config import Settings

logger = logging.getLogger(__name__)


class ContextManager:

    def __init__(self, max_history: int = None):
        if max_history is None:
            max_history = Settings().config.limits.context.max_history
        self.max_history = max_history
        self.contexts: Dict[str, List[Dict]] = {}
        self.system_prompts: Dict[str, str] = {}
        self.system_prompt_sent: Dict[str, bool] = {}

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
        if session_id in self.system_prompt_sent:
            del self.system_prompt_sent[session_id]

    def set_system_prompt(self, session_id: str, prompt: str):
        self.system_prompts[session_id] = prompt
        self.system_prompt_sent[session_id] = False
        logger.debug(f"Set system prompt for session {session_id}: {len(prompt)} chars")

    def get_system_prompt(self, session_id: str) -> str:
        return self.system_prompts.get(session_id, "")

    def mark_system_prompt_as_sent(self, session_id: str):
        self.system_prompt_sent[session_id] = True

    def is_system_prompt_sent(self, session_id: str) -> bool:
        return self.system_prompt_sent.get(session_id, False)

    def get_context_with_system_prompt(self, session_id: str, include_system_prompt: bool = True) -> List[Dict]:
        messages = []
        system_prompt = self.get_system_prompt(session_id)

        if system_prompt and include_system_prompt and not self.is_system_prompt_sent(session_id):
            messages.append({"role": "system", "content": system_prompt})
            self.mark_system_prompt_as_sent(session_id)
            logger.debug(f"System prompt included for session {session_id}")

        messages.extend(self.get_context(session_id))
        return messages

    def get_context_str(self, session_id: str) -> str:
        messages = self.get_context(session_id)
        if not messages:
            return ""

        parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            parts.append(f"{role}: {content}")

        return "\n".join(parts)


_context_manager = ContextManager()


def get_context_manager() -> ContextManager:
    return _context_manager
