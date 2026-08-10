"""
server/protocol/message.py 回归测试
WebSocket 消息协议模型与工厂函数
"""
import pytest
from pydantic import ValidationError

from server.protocol.message import (
    BaseMessage,
    ErrorMessage,
    MessageType,
    PingMessage,
    PongMessage,
    RequestMessage,
    ResponseMessage,
    StreamMessage,
    create_error,
    create_pong,
    create_request,
    create_response,
    create_stream,
)


class TestBaseMessage:
    def test_default_fields(self):
        m = BaseMessage(type=MessageType.REQUEST)
        assert m.type == MessageType.REQUEST
        assert m.request_id is not None
        assert m.action is None
        assert m.timestamp > 0

    def test_request_id_auto_generated_unique(self):
        m1 = BaseMessage(type=MessageType.REQUEST)
        m2 = BaseMessage(type=MessageType.REQUEST)
        assert m1.request_id != m2.request_id

    def test_missing_type_raises(self):
        with pytest.raises(ValidationError):
            BaseMessage()


class TestRequestMessage:
    def test_defaults(self):
        m = RequestMessage(action="chat.message")
        assert m.type == MessageType.REQUEST
        assert m.data == {}

    def test_invalid_type_raises(self):
        with pytest.raises(ValidationError):
            RequestMessage(action="x", type="bad")


class TestResponseMessage:
    def test_defaults(self):
        m = ResponseMessage(action="chat.message")
        assert m.type == MessageType.RESPONSE
        assert m.status == "success"
        assert m.data == {}


class TestStreamMessage:
    def test_defaults(self):
        m = StreamMessage(action="tts.stream")
        assert m.type == MessageType.STREAM
        assert m.chunk_index == 0
        assert m.is_final is False


class TestErrorMessage:
    def test_defaults(self):
        m = ErrorMessage(action="x")
        assert m.type == MessageType.ERROR
        assert m.error == {}


class TestPingPong:
    def test_ping(self):
        m = PingMessage()
        assert m.type == MessageType.PING

    def test_pong(self):
        m = PongMessage()
        assert m.type == MessageType.PONG


class TestFactoryFunctions:
    def test_create_response(self):
        d = create_response("rid-1", "chat.message", {"ok": True})
        assert d["request_id"] == "rid-1"
        assert d["action"] == "chat.message"
        assert d["status"] == "success"
        assert d["type"] == MessageType.RESPONSE.value
        assert d["data"] == {"ok": True}

    def test_create_response_custom_status(self):
        d = create_response("r", "a", {}, status="error")
        assert d["status"] == "error"

    def test_create_request_defaults(self):
        d = create_request("tools.list", {})
        assert d["action"] == "tools.list"
        assert d["type"] == MessageType.REQUEST.value
        assert d["data"] == {}
        # 工厂函数未传 request_id 时透传 None（模型默认值仅在直接构造时生效）
        assert d["request_id"] is None

    def test_create_request_with_id_and_data(self):
        d = create_request("tools.call", {"name": "x"}, request_id="fixed")
        assert d["request_id"] == "fixed"
        assert d["data"] == {"name": "x"}

    def test_create_stream(self):
        d = create_stream("r", "tts.stream", 3, {"text": "hi"}, is_final=True)
        assert d["chunk_index"] == 3
        assert d["is_final"] is True
        assert d["data"] == {"text": "hi"}

    def test_create_stream_default_final(self):
        d = create_stream("r", "a", 0, {})
        assert d["is_final"] is False

    def test_create_error(self):
        d = create_error("r", "chat.message", "E001", "boom")
        assert d["type"] == MessageType.ERROR.value
        assert d["error"] == {"code": "E001", "message": "boom"}

    def test_create_pong(self):
        d = create_pong(123.0)
        assert d["type"] == MessageType.PONG.value
        assert d["timestamp"] == 123.0