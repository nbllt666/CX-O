"""
情感标记解析模块
解析文本中的情感标记，格式为【emotion】（全角方括号）
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_EMOTIONS = frozenset([
    "normal",
    "happy",
    "sad",
    "angry",
    "surprised",
    "fearful",
    "disgusted",
    "tender"
])

EMOTION_PATTERN = re.compile(r"【([a-zA-Z]+)】")

EMOTION_PROMPTS: dict[str, str] = {
    "normal": "用平静、自然的语气说话",
    "happy": "用开心、愉快的语气说话，表达积极情绪",
    "sad": "用悲伤、低沉的语气说话，表达失落情绪",
    "angry": "用愤怒、激动的语气说话，表达不满情绪",
    "surprised": "用惊讶、意外的语气说话，表达震惊情绪",
    "fearful": "用恐惧、紧张的语气说话，表达害怕情绪",
    "disgusted": "用厌恶、反感的语气说话，表达不喜欢情绪",
    "tender": "用温柔、柔和的语气说话，表达关爱情绪"
}


def get_supported_emotions() -> list[str]:
    return list(SUPPORTED_EMOTIONS)


def parse_text_with_emotions(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    
    result: list[dict[str, Any]] = []
    last_end = 0
    
    for match in EMOTION_PATTERN.finditer(text):
        start = match.start()
        end = match.end()
        emotion = match.group(1).lower()
        
        if start > last_end:
            content = text[last_end:start]
            if content:
                result.append({
                    "type": "text",
                    "content": content
                })
        
        if emotion in SUPPORTED_EMOTIONS:
            result.append({
                "type": "emotion",
                "emotion": emotion
            })
        else:
            logger.warning(f"Unknown emotion tag: {emotion}, treating as text")
            result.append({
                "type": "text",
                "content": match.group(0)
            })
        
        last_end = end
    
    if last_end < len(text):
        content = text[last_end:]
        if content:
            result.append({
                "type": "text",
                "content": content
            })
    
    return result


def generate_emotion_prompt(
    segments: list[dict[str, Any]] | None = None,
    text: str | None = None,
    default_emotion: str = "normal"
) -> str:
    if segments is None and text is not None:
        segments = parse_text_with_emotions(text)
    
    if not segments:
        return EMOTION_PROMPTS.get(default_emotion, EMOTION_PROMPTS["normal"])
    
    emotion_prompts = []
    current_emotion = default_emotion
    
    for segment in segments:
        if segment["type"] == "emotion":
            current_emotion = segment["emotion"]
        elif segment["type"] == "text":
            content = segment["content"].strip()
            if content:
                prompt = EMOTION_PROMPTS.get(current_emotion, EMOTION_PROMPTS["normal"])
                emotion_prompts.append(f"[{prompt}] {content}")
    
    if not emotion_prompts:
        return EMOTION_PROMPTS.get(default_emotion, EMOTION_PROMPTS["normal"])
    
    return "\n".join(emotion_prompts)


def get_current_emotion(segments: list[dict[str, Any]], default: str = "normal") -> str:
    current = default
    for segment in segments:
        if segment["type"] == "emotion":
            current = segment["emotion"]
    return current


def strip_emotion_tags(text: str) -> str:
    return EMOTION_PATTERN.sub("", text)


def extract_emotions_with_text(text: str) -> list[tuple[str, str]]:
    segments = parse_text_with_emotions(text)
    result: list[tuple[str, str]] = []
    current_emotion = "normal"
    
    for segment in segments:
        if segment["type"] == "emotion":
            current_emotion = segment["emotion"]
        elif segment["type"] == "text":
            content = segment["content"].strip()
            if content:
                result.append((current_emotion, content))
    
    return result
