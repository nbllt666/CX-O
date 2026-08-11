"""
server/services/frontend_marker.py 回归测试
前端标记适配器：情感/音效 → 前端格式转换
"""
import pytest

from server.services.frontend_marker import FrontendMarker, get_frontend_marker


@pytest.fixture
def marker():
    return FrontendMarker()


class TestFormatForFrontend:
    def test_empty_data_returns_copy(self, marker):
        result = marker.format_for_frontend({})
        assert result == {}

    def test_emotion_conversion(self, marker):
        result = marker.format_for_frontend({"emotion": "happy"})
        assert result["emotion"] == "happy"
        assert result["frontend_emotion"] == {"type": "positive", "intensity": 0.8}

    def test_effect_conversion(self, marker):
        result = marker.format_for_frontend({"effect": "thunder"})
        assert result["frontend_effect"] == {"type": "weather", "volume": 0.8}

    def test_original_fields_preserved(self, marker):
        result = marker.format_for_frontend({"emotion": "calm", "text": "hi"})
        assert result["text"] == "hi"
        assert result["frontend_emotion"] is not None

    def test_markers_list_emotion_and_effect_decorated(self, marker):
        # process_danmaku / process_message 的真实产出形态：markers 列表
        data = {
            "type": "danmaku",
            "content": "[emotion:happy]（敲门声）",
            "markers": [
                {"type": "emotion", "name": "happy", "position": 0},
                {"type": "effect", "name": "door", "position": 13},
            ],
        }
        result = marker.format_for_frontend(data)
        assert result["markers"][0]["frontend_emotion"] == {"type": "positive", "intensity": 0.8}
        assert result["markers"][1]["frontend_effect"] == {"type": "ambient", "volume": 0.5}
        # 原始 markers 不被原地污染
        assert "frontend_emotion" not in data["markers"][0]

    def test_markers_list_untouched_when_no_emotion_effect(self, marker):
        data = {"type": "danmaku", "content": "普通弹幕", "markers": []}
        result = marker.format_for_frontend(data)
        assert result["markers"] == []


class TestConvertEmotion:
    def test_known_emotions(self):
        marker = FrontendMarker()
        assert marker._convert_emotion("happy")["type"] == "positive"
        assert marker._convert_emotion("sad")["type"] == "negative"
        assert marker._convert_emotion("angry")["intensity"] == 0.9
        assert marker._convert_emotion("neutral") == {"type": "neutral", "intensity": 0.3}

    def test_unknown_emotion_falls_back(self, marker):
        # 未知情感 → neutral 兜底
        assert marker._convert_emotion("nonexistent") == {"type": "neutral", "intensity": 0.3}


class TestConvertEffect:
    def test_known_effects(self):
        marker = FrontendMarker()
        assert marker._convert_effect("rain") == {"type": "weather", "volume": 0.5}
        assert marker._convert_effect("door")["type"] == "ambient"

    def test_unknown_effect_falls_back(self, marker):
        assert marker._convert_effect("unknown") == {"type": "custom", "volume": 0.5}


class TestSingleton:
    def test_get_frontend_marker_is_singleton(self):
        assert get_frontend_marker() is get_frontend_marker()