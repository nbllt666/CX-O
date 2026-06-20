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
        include_markers: bool = True,
        is_realtime_voice: bool = False,
    ) -> list[dict]:
        # 实时语音模式：走专用裁剪分支，确保 Prompt Tokens < 500，锁死 80ms TTFT
        if is_realtime_voice:
            return self._build_realtime_messages(
                user_text=user_text,
                context=context,
                system_prompt=system_prompt,
            )

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
        agent_config: dict | None = None,
        is_realtime_voice: bool = False,
    ) -> list[dict]:
        # 实时语音模式：走专用裁剪分支，跳过 personality 等额外系统提示词
        if is_realtime_voice:
            return self._build_realtime_messages(
                user_text=user_text,
                context=context,
                system_prompt=(agent_config or {}).get("system_prompt", ""),
            )

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

    def _build_realtime_messages(
        self,
        user_text: str,
        context: list[dict] | None = None,
        system_prompt: str | None = None,
    ) -> list[dict]:
        """
        实时语音模式专用消息构建器。

        设计目标：Prompt Tokens < 500，锁死 80ms TTFT。
        - 仅保留核心 System Prompt（不注入 personality / tool_instructions 等重型提示词，
          省去 ~1500 tokens 的 Prefill，对应节省 100-200ms）
        - 仅保留最近 2 轮对话上下文（limit=4，即 2 user + 2 assistant），
          避免长历史导致 Prefill 线性膨胀
        - realtime_voice_prompt 由上层 chat.py 注入，这里只负责不重复注入重型内容
        """
        messages: list[dict] = []

        # 核心系统提示词：保留 agent 自身的 system_prompt，确保人设不丢
        prompt = system_prompt or self._system_prompt
        if prompt:
            messages.append({"role": "system", "content": prompt})

        # 仅保留最近 2 轮对话（4 条消息），避免长历史 Prefill 膨胀
        # 每多 1K tokens 历史约增加 20-40ms Prefill，裁剪到 4 条可省 60-120ms
        if context:
            trimmed_context = context[-4:] if len(context) > 4 else context
            messages.extend(trimmed_context)

        # 实时模式下不做 emotion/effect 标记清洗，直接送原文，避免正则开销
        messages.append({"role": "user", "content": user_text})

        return messages


_prompt_builder: Optional[PromptBuilder] = None


def get_prompt_builder() -> PromptBuilder:
    global _prompt_builder
    if _prompt_builder is None:
        _prompt_builder = PromptBuilder()
    return _prompt_builder
