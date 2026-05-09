"""
隐藏提示词模块
管理需要注入到对话上下文中的隐藏系统提示词
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class HiddenPromptManager:
    _instance = None

    def __init__(self):
        self._prompts: dict[str, str] = {}
        self._enabled = True

    @classmethod
    def get_instance(cls) -> "HiddenPromptManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_enabled(self, enabled: bool):
        self._enabled = enabled

    def register_prompt(self, name: str, prompt: str):
        self._prompts[name] = prompt
        logger.debug(f"Registered hidden prompt: {name}")

    def remove_prompt(self, name: str):
        if name in self._prompts:
            del self._prompts[name]
            logger.debug(f"Removed hidden prompt: {name}")

    def get_prompt(self, name: str) -> Optional[str]:
        return self._prompts.get(name)

    def get_all_prompts(self) -> dict[str, str]:
        return self._prompts.copy()

    def build_system_prompt_extension(self) -> str:
        if not self._enabled:
            return ""

        parts = []
        for name, prompt in self._prompts.items():
            parts.append(prompt)

        return "\n\n".join(parts)

    def inject_into_context(self, context: list[dict]) -> list[dict]:
        if not self._enabled:
            return context

        extension = self.build_system_prompt_extension()
        if not extension:
            return context

        for msg in context:
            if msg.get("role") == "system":
                msg["content"] = msg.get("content", "") + "\n\n" + extension
                return context

        context.insert(0, {"role": "system", "content": extension})
        return context


def get_hidden_prompt_manager() -> HiddenPromptManager:
    return HiddenPromptManager.get_instance()
