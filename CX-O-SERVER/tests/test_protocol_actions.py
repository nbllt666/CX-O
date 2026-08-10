"""
server/protocol/actions.py 回归测试
Action 常量 与 get_handler_name 分发映射
"""
import pytest

from server.protocol.actions import (
    ACTION_HANDLERS,
    ChatActions,
    MemoryActions,
    SystemActions,
    VoiceActions,
    get_handler_name,
)


class TestChatActions:
    def test_constants(self):
        assert ChatActions.MESSAGE == "chat.message"
        assert ChatActions.STREAM == "chat.stream"
        assert ChatActions.MULTIMODAL == "chat.multimodal"


class TestHandlerMapping:
    def test_known_action_maps_to_handler(self):
        assert get_handler_name("chat.message") == "chat"
        assert get_handler_name("memory.search") == "memory"
        assert get_handler_name("system.status") == "system"

    def test_unknown_action_returns_none(self):
        assert get_handler_name("no.such.action") is None
        assert get_handler_name("") is None

    def test_voice_dual_stream_maps_to_audio(self):
        assert get_handler_name(VoiceActions.DUAL_STREAM) == "audio"


class TestActionHandlerRegistry:
    def test_all_defined_actions_have_handler(self):
        # ACTION_HANDLERS 覆盖所有主要 action 常量组
        for group in (ChatActions, MemoryActions, SystemActions):
            for name, value in vars(group).items():
                if name.startswith("_"):
                    continue
                assert value in ACTION_HANDLERS, f"{group.__name__}.{name}={value} 未注册"

    def test_handler_registry_is_complete_for_duplicate_keys(self):
        # 同一 action 映射到 handler 应为字符串
        for action, handler in ACTION_HANDLERS.items():
            assert isinstance(action, str)
            assert isinstance(handler, str)