"""
情感解析器
解析文本中的情感标记 [emotion:name] 并提取情感信息
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

EMOTION_PATTERN = re.compile(r'\[emotion:([^\]]+)\]')
COMBINED_PATTERN = re.compile(r'\[(?:emotion:([^\]]+)|sleep:(\d+))\]')

SUPPORTED_EMOTIONS = {
    "happy", "sad", "angry", "surprised", "fear",
    "disgust", "neutral", "excited", "calm", "whisper",
    "shout", "laugh", "cry", "sigh", "giggle",
}


def get_supported_emotions() -> list[str]:
    """返回全部受支持的情感名称（已排序）。"""
    return sorted(SUPPORTED_EMOTIONS)


def extract_emotions_with_text(text: str) -> list[dict[str, Any]]:
    """解析文本中的 [emotion:name] 与 [sleep:ms] 标记，返回文本与情感/停顿分段。"""

    segments: list[dict[str, Any]] = []
    last_end = 0

    for match in COMBINED_PATTERN.finditer(text):
        if match.start() > last_end:
            text_before = text[last_end:match.start()].strip()
            if text_before:
                segments.append({
                    "type": "text",
                    "content": text_before
                })

        emotion_name = match.group(1)
        sleep_ms = match.group(2)

        if emotion_name is not None:
            emotion_name = emotion_name.lower()
            if emotion_name in SUPPORTED_EMOTIONS:
                segments.append({
                    "type": "emotion",
                    "emotion": emotion_name
                })
            else:
                logger.warning(f"Unknown emotion: {emotion_name}")
                segments.append({
                    "type": "text",
                    "content": match.group(0)
                })
        elif sleep_ms is not None:
            segments.append({
                "type": "sleep",
                "duration_ms": int(sleep_ms)
            })

        last_end = match.end()

    if last_end < len(text):
        remaining_text = text[last_end:].strip()
        if remaining_text:
            segments.append({
                "type": "text",
                "content": remaining_text
            })

    return segments
