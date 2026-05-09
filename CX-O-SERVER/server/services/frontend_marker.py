"""
前端标记适配器
将内部消息标记转换为前端可识别的格式
"""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class FrontendMarker:
    def __init__(self):
        self._markers: dict[str, Any] = {}

    def register_marker(self, name: str, handler: Any):
        self._markers[name] = handler

    def format_for_frontend(self, data: dict) -> dict:
        result = data.copy()

        if "emotion" in result:
            result["frontend_emotion"] = self._convert_emotion(result["emotion"])

        if "effect" in result:
            result["frontend_effect"] = self._convert_effect(result["effect"])

        return result

    def _convert_emotion(self, emotion: str) -> dict:
        emotion_map = {
            "happy": {"type": "positive", "intensity": 0.8},
            "sad": {"type": "negative", "intensity": 0.6},
            "angry": {"type": "negative", "intensity": 0.9},
            "surprised": {"type": "neutral", "intensity": 0.7},
            "fear": {"type": "negative", "intensity": 0.8},
            "disgust": {"type": "negative", "intensity": 0.7},
            "neutral": {"type": "neutral", "intensity": 0.3},
            "excited": {"type": "positive", "intensity": 0.9},
            "calm": {"type": "positive", "intensity": 0.4},
            "whisper": {"type": "neutral", "intensity": 0.3},
            "shout": {"type": "neutral", "intensity": 0.9},
            "laugh": {"type": "positive", "intensity": 0.7},
            "cry": {"type": "negative", "intensity": 0.8},
            "sigh": {"type": "neutral", "intensity": 0.4},
            "giggle": {"type": "positive", "intensity": 0.5},
        }
        return emotion_map.get(emotion, {"type": "neutral", "intensity": 0.3})

    def _convert_effect(self, effect: str) -> dict:
        effect_map = {
            "thunder": {"type": "weather", "volume": 0.8},
            "rain": {"type": "weather", "volume": 0.5},
            "wind": {"type": "weather", "volume": 0.6},
            "footsteps": {"type": "ambient", "volume": 0.4},
            "door": {"type": "ambient", "volume": 0.5},
            "phone": {"type": "ambient", "volume": 0.6},
        }
        return effect_map.get(effect, {"type": "custom", "volume": 0.5})


_frontend_marker: Optional[FrontendMarker] = None


def get_frontend_marker() -> FrontendMarker:
    global _frontend_marker
    if _frontend_marker is None:
        _frontend_marker = FrontendMarker()
    return _frontend_marker
