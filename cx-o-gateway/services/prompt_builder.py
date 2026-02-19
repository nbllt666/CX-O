"""
系统提示词生成模块
生成包含情感指导和音效指导的系统提示词
"""
import logging
from pathlib import Path
from typing import Any

from .emotion_parser import EMOTION_PROMPTS, SUPPORTED_EMOTIONS
from .effect_parser import EffectParser

logger = logging.getLogger(__name__)


class PromptBuilder:
    def __init__(
        self,
        effects_dir: str | Path | None = None,
        enable_emotion: bool = True,
        enable_effect: bool = True
    ):
        self._enable_emotion = enable_emotion
        self._enable_effect = enable_effect
        self._effect_parser = EffectParser(effects_dir) if enable_effect else None

    @property
    def enable_emotion(self) -> bool:
        return self._enable_emotion

    @enable_emotion.setter
    def enable_emotion(self, value: bool) -> None:
        self._enable_emotion = value

    @property
    def enable_effect(self) -> bool:
        return self._enable_effect

    @enable_effect.setter
    def enable_effect(self, value: bool) -> None:
        self._enable_effect = value
        if value and self._effect_parser is None:
            self._effect_parser = EffectParser()

    def _generate_emotion_section(self) -> str:
        emotion_items = []
        for emotion in sorted(SUPPORTED_EMOTIONS):
            if emotion in EMOTION_PROMPTS:
                emotion_items.append(f"- 【{emotion}】{EMOTION_PROMPTS[emotion].replace('用', '').replace('语气说话', '').replace('，', '/').replace('表达', '')}")

        emotion_list = "\n".join(emotion_items)
        
        section = f"""## 情感表达
你可以在回复中使用情感标记来表达不同的情感：
{emotion_list}

使用示例：【happy】太棒了！这个消息真让人高兴！

注意：情感标记应放在对应文本之前，用于指导语音合成时的情感表达。"""
        
        return section

    def _generate_effect_section(self) -> str:
        if not self._effect_parser:
            return ""
        
        available_effects = self._effect_parser.get_available_effects()
        if not available_effects:
            return ""
        
        effect_names = [effect["name"] for effect in available_effects]
        effect_list = "\n".join([f"- （{name}）" for name in sorted(effect_names)])
        
        section = f"""## 可用音效
在回复中可以使用以下音效标记来插入音效：
{effect_list}

格式：（音效名）
示例：你好（ding）很高兴见到你！

注意：请仅在合适场景使用音效，不要过度使用。"""
        
        return section

    def generate_system_prompt(
        self,
        base_prompt: str = "",
        enable_emotion: bool | None = None,
        enable_effect: bool | None = None
    ) -> str:
        use_emotion = enable_emotion if enable_emotion is not None else self._enable_emotion
        use_effect = enable_effect if enable_effect is not None else self._enable_effect
        
        sections: list[str] = []
        
        if base_prompt:
            sections.append(base_prompt)
        
        if use_emotion:
            emotion_section = self._generate_emotion_section()
            if emotion_section:
                sections.append(emotion_section)
        
        if use_effect:
            effect_section = self._generate_effect_section()
            if effect_section:
                sections.append(effect_section)
        
        return "\n\n".join(sections)

    def get_available_effects(self) -> list[dict[str, str]]:
        if not self._effect_parser:
            return []
        return self._effect_parser.get_available_effects()

    def rescan_effects(self) -> None:
        if self._effect_parser:
            self._effect_parser.rescan_effects()

    def get_supported_emotions(self) -> list[str]:
        return list(SUPPORTED_EMOTIONS)


def generate_system_prompt(
    base_prompt: str = "",
    effects_dir: str | Path | None = None,
    enable_emotion: bool = True,
    enable_effect: bool = True
) -> str:
    builder = PromptBuilder(
        effects_dir=effects_dir,
        enable_emotion=enable_emotion,
        enable_effect=enable_effect
    )
    return builder.generate_system_prompt(base_prompt=base_prompt)
