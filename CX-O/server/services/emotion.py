import re
from typing import Any

EMOTION_PATTERN = re.compile(r"\[(emotion:\s*(\w+))\](.*?)\[/emotion\]", re.IGNORECASE | re.DOTALL)


def extract_emotions_with_text(text: str) -> list[tuple[str, str]]:
    emotions = []
    matches = EMOTION_PATTERN.findall(text)

    for match in matches:
        full_match, emotion, content = match
        emotions.append((emotion.lower().strip(), content.strip()))

    return emotions


def parse_text_with_emotions(text: str) -> list[dict[str, Any]]:
    result = []

    last_end = 0
    for match in EMOTION_PATTERN.finditer(text):
        start, end = match.span()

        if start > last_end:
            text_content = text[last_end:start].strip()
            if text_content:
                result.append({"type": "text", "content": text_content})

        full_match, emotion, content = match.groups()
        result.append({"type": "emotion", "emotion": emotion.lower().strip(), "content": content.strip()})

        last_end = end

    if last_end < len(text):
        remaining_text = text[last_end:].strip()
        if remaining_text:
            result.append({"type": "text", "content": remaining_text})

    return result


def get_supported_emotions() -> list[dict[str, str]]:
    return [
        {"id": "happy", "name": "开心", "icon": "😊"},
        {"id": "sad", "name": "悲伤", "icon": "😢"},
        {"id": "angry", "name": "愤怒", "icon": "😠"},
        {"id": "neutral", "name": "平静", "icon": "😐"},
        {"id": "fearful", "name": "恐惧", "icon": "😨"},
        {"id": "disgusted", "name": "厌恶", "icon": "😒"},
        {"id": "surprised", "name": "惊讶", "icon": "😮"},
    ]
