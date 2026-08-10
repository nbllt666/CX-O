"""
server/services/marker_adapter.py 回归测试
标记适配器：文本 → 统一消息格式 + 标记提取
"""
import pytest

from server.services.marker_adapter import MarkerAdapter


@pytest.fixture
def adapter():
    return MarkerAdapter()


class TestProcessDanmaku:
    def test_basic_fields(self, adapter):
        data = {"user": {"id": 1}, "content": "hello", "timestamp": 123}
        result = adapter.process_danmaku(data)
        assert result["type"] == "danmaku"
        assert result["user"] == {"id": 1}
        assert result["content"] == "hello"
        assert result["timestamp"] == 123
        assert result["markers"] == []

    def test_missing_fields_default(self, adapter):
        result = adapter.process_danmaku({})
        assert result["user"] == {}
        assert result["content"] == ""
        assert result["timestamp"] == 0

    def test_emotion_marker_extraction(self, adapter):
        result = adapter.process_danmaku({"content": "哈哈[emotion:happy]好"})
        markers = result["markers"]
        assert any(m["type"] == "emotion" and m["name"] == "happy" for m in markers)

    def test_effect_marker_extraction(self, adapter):
        result = adapter.process_danmaku({"content": "[effect:thunder]来了"})
        markers = result["markers"]
        assert any(m["type"] == "effect" and m["name"] == "thunder" for m in markers)

    def test_marker_position(self, adapter):
        result = adapter.process_danmaku({"content": "前缀[emotion:happy]后缀"})
        emotion_marker = next(m for m in result["markers"])
        assert emotion_marker["position"] == 2


class TestProcessMessage:
    def test_default_type_text(self, adapter):
        result = adapter.process_message({"content": "hi"})
        assert result["type"] == "text"
        assert result["content"] == "hi"
        assert result["markers"] == []

    def test_type_preserved(self, adapter):
        result = adapter.process_message({"type": "assistant", "content": "hi"})
        assert result["type"] == "assistant"

    def test_emotion_and_effect_markers(self, adapter):
        result = adapter.process_message({"content": "[emotion:happy][effect:rain]"})
        types = {m["type"] for m in result["markers"]}
        assert types == {"emotion", "effect"}

    def test_action_marker(self, adapter):
        result = adapter.process_message({"content": "[action:join_room]"})
        assert any(m["type"] == "action" and m["name"] == "join_room" for m in result["markers"])

    def test_no_brackets_no_markers(self, adapter):
        result = adapter.process_message({"content": "plain text"})
        assert result["markers"] == []


class TestSupportedMarkers:
    def test_returns_copy(self, adapter):
        markers = adapter.get_supported_markers()
        assert markers == ["emotion", "effect", "action", "danmaku", "gift", "enter", "system"]
        # 返回副本，修改不影响内部状态
        markers.append("x")
        assert "x" not in adapter.get_supported_markers()