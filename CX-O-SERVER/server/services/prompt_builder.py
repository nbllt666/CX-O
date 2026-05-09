"""
提示词构建器
根据上下文和配置构建发送给 LLM 的提示词
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .emotion_parser import strip_emotion_tags
from .effect_parser import EffectParser

logger = logging.getLogger(__name__)


class PromptBuilder:
    def __init__(self):
        self._system_prompt: str = ""
        self._emotion_parser = None
        self._effect_parser: Optional[EffectParser] = None

    def set_system_prompt(self, prompt: str):
        self._system_prompt = prompt

    def set_effect_parser(self, effect_parser: EffectParser):
        self._effect_parser = effect_parser

    def build_messages(
        self,
        user_text: str,
        context: list[dict] | None = None,
        system_prompt: str | None = None,
        include_markers: bool = True
    ) -> list[dict]:
        messages = []

        prompt = system_prompt or self._system_prompt
        if prompt:
            messages.append({"role": "system", "content": prompt})

        if context:
            messages.extend(context)

        clean_text = user_text
        if not include_markers:
            clean_text = strip_emotion_tags(clean_text)
            if self._effect_parser:
                import re
                clean_text = re.sub(r'\[effect:([^\]]+)\]', '', clean_text).strip()

        messages.append({"role": "user", "content": clean_text})

        return messages

    def build_chat_prompt(
        self,
        user_text: str,
        context: list[dict] | None = None,
        agent_config: dict | None = None
    ) -> list[dict]:
        messages = []

        if agent_config:
            system_prompt = agent_config.get("system_prompt", "")
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})

            personality = agent_config.get("personality", "")
            if personality:
                messages.append({"role": "system", "content": f"性格设定: {personality}"})

        if context:
            messages.extend(context)

        messages.append({"role": "user", "content": user_text})

        return messages


_prompt_builder: Optional[PromptBuilder] = None


def get_prompt_builder() -> PromptBuilder:
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = PromptBuilder()
    return _prompt_builder
