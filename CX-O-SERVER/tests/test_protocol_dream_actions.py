"""
server/protocol/actions.py DreamActions 回归测试

覆盖（spec "WebSocket 协议"）：
1. 6 个 DreamActions 常量值断言
2. get_handler_name("dream.confirm" / "dream.reject") 映射到 "dream"
3. ACTION_HANDLERS 含 dream 键（C→S 入向）

运行：python -m pytest tests/test_protocol_dream_actions.py -q
"""
from server.protocol.actions import (
    ACTION_HANDLERS,
    DreamActions,
    get_handler_name,
)


class TestDreamActionsConstants:
    """6 个 DreamActions 常量值。"""

    def test_constants(self):
        assert DreamActions.SESSION_STARTED == "dream.session_started"
        assert DreamActions.SESSION_COMPLETED == "dream.session_completed"
        assert DreamActions.SURFACE == "dream.surface"
        assert DreamActions.CONFIRM == "dream.confirm"
        assert DreamActions.REJECT == "dream.reject"
        assert DreamActions.PURGED == "dream.purged"


class TestDreamHandlerMapping:
    """get_handler_name 分发映射（C→S 入向）。"""

    def test_confirm_maps_to_dream(self):
        assert get_handler_name(DreamActions.CONFIRM) == "dream"

    def test_reject_maps_to_dream(self):
        assert get_handler_name(DreamActions.REJECT) == "dream"

    def test_confirm_maps_to_dream_by_literal(self):
        # 字符串字面量同样可解析（对齐既有映射风格）
        assert get_handler_name("dream.confirm") == "dream"
        assert get_handler_name("dream.reject") == "dream"

    def test_surface_is_push_only_not_registered(self):
        # S→C 推送 action 不入 ACTION_HANDLERS（非 C→S 入向，type 直发）
        assert get_handler_name(DreamActions.SURFACE) is None
        assert get_handler_name(DreamActions.SESSION_STARTED) is None
        assert get_handler_name(DreamActions.SESSION_COMPLETED) is None
        assert get_handler_name(DreamActions.PURGED) is None


class TestDreamActionHandlerRegistry:
    """ACTION_HANDLERS 含 dream 键。"""

    def test_confirm_and_reject_registered(self):
        assert DreamActions.CONFIRM in ACTION_HANDLERS
        assert DreamActions.REJECT in ACTION_HANDLERS
        assert ACTION_HANDLERS[DreamActions.CONFIRM] == "dream"
        assert ACTION_HANDLERS[DreamActions.REJECT] == "dream"

    def test_handler_value_is_string(self):
        for action in (DreamActions.CONFIRM, DreamActions.REJECT):
            assert isinstance(ACTION_HANDLERS[action], str)
