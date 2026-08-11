"""
前端标记适配器
将内部消息标记转换为前端可识别的格式
"""
import logging
from typing import Any, Optional

from server.services.emotion_parser import SUPPORTED_EMOTIONS

logger = logging.getLogger(__name__)

# 情感/音效 → 前端展示映射，模块级常量避免弹幕热路径每次调用重建 dict
_NEUTRAL_EMOTION = {"type": "neutral", "intensity": 0.3}
_EMOTION_MAP: dict[str, dict[str, Any]] = {
    "happy": {"type": "positive", "intensity": 0.8},
    "sad": {"type": "negative", "intensity": 0.6},
    "angry": {"type": "negative", "intensity": 0.9},
    "surprised": {"type": "neutral", "intensity": 0.7},
    "fear": {"type": "negative", "intensity": 0.8},
    "disgust": {"type": "negative", "intensity": 0.7},
    "neutral": _NEUTRAL_EMOTION,
    "excited": {"type": "positive", "intensity": 0.9},
    "calm": {"type": "positive", "intensity": 0.4},
    "whisper": {"type": "neutral", "intensity": 0.3},
    "shout": {"type": "neutral", "intensity": 0.9},
    "laugh": {"type": "positive", "intensity": 0.7},
    "cry": {"type": "negative", "intensity": 0.8},
    "sigh": {"type": "neutral", "intensity": 0.4},
    "giggle": {"type": "positive", "intensity": 0.5},
}
_EFFECT_MAP: dict[str, dict[str, Any]] = {
    "thunder": {"type": "weather", "volume": 0.8},
    "rain": {"type": "weather", "volume": 0.5},
    "wind": {"type": "weather", "volume": 0.6},
    "footsteps": {"type": "ambient", "volume": 0.4},
    "door": {"type": "ambient", "volume": 0.5},
    "phone": {"type": "ambient", "volume": 0.6},
}
_CUSTOM_EFFECT: dict[str, Any] = {"type": "custom", "volume": 0.5}


class FrontendMarker:
    def format_for_frontend(self, data: dict) -> dict:
        """将内部标记转换为前端可识别格式。

        两种输入形态均处理：
        1. markers 列表（process_danmaku / process_message 的真实产出，含 type/name）
        2. 顶层 emotion/effect 键（历史形态，兼容保留）

        对每个 emotion/effect 标记追加 frontend_emotion / frontend_effect 展示数据。
        """
        result = data.copy()

        # markers 列表：逐条为 emotion/effect 标记附加前端展示字段
        markers = result.get("markers")
        if markers:
            result["markers"] = [
                self._decorate_marker(dict(marker))
                for marker in markers
            ]

        # 顶层 emotion/effect 键（历史兼容）
        if "emotion" in result:
            result["frontend_emotion"] = self._convert_emotion(result["emotion"])
        if "effect" in result:
            result["frontend_effect"] = self._convert_effect(result["effect"])

        return result

    def _decorate_marker(self, marker: dict) -> dict:
        mtype = marker.get("type")
        name = marker.get("name", "")
        if mtype == "emotion":
            marker["frontend_emotion"] = self._convert_emotion(name)
        elif mtype == "effect":
            marker["frontend_effect"] = self._convert_effect(name)
        return marker

    def _convert_emotion(self, emotion: str) -> dict:
        if emotion not in SUPPORTED_EMOTIONS:
            logger.warning(f"Unknown emotion not in SUPPORTED_EMOTIONS: {emotion}")
            return _NEUTRAL_EMOTION
        return _EMOTION_MAP.get(emotion, _NEUTRAL_EMOTION)

    def _convert_effect(self, effect: str) -> dict:
        return _EFFECT_MAP.get(effect, _CUSTOM_EFFECT)


_frontend_marker: Optional[FrontendMarker] = None


def get_frontend_marker() -> FrontendMarker:
    global _frontend_marker
    if _frontend_marker is None:
        _frontend_marker = FrontendMarker()
    return _frontend_marker
