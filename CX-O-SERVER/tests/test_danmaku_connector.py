"""观众弹幕连接器单元测试（T3.4）。

用假连接器 / 直接调用解析方法完成验证，不真实连外网：
- RdfConnector 解析：文本行（username: message）与 JSON 两种
- create_connector 工厂：none→None、未知→ValueError、rdf/bilibili→对应类
- start/stop 生命周期：假连接器子类（覆盖 _run 不联网）

运行：python -m pytest tests/test_danmaku_connector.py -v
"""
import asyncio

import pytest

from server.core.meeting.danmaku_connector import (
    BilibiliConnector,
    DanmakuConnector,
    RdfConnector,
    create_connector,
)


# ================================================================ 解析
class TestRdfParse:
    def test_text_line_format(self):
        """文本行 `username: message` 解析出 (userid, username, text)。"""
        conn = RdfConnector("ws://x", on_danmaku=None)
        parsed = conn._parse_line("主播你好")
        assert parsed is None
        parsed = conn._parse_line("水友1: 大家好呀")
        assert parsed == ("", "水友1", "大家好呀")

    def test_json_format(self):
        """JSON（user/username + msg/text）解析出对应三元组。"""
        conn = RdfConnector("ws://x", on_danmaku=None)
        assert conn._parse_line('{"user": "张三", "msg": "晚上好"}') == ("", "张三", "晚上好")
        assert conn._parse_line('{"username": "李四", "text": "注意安全", "userid": "u9"}') == (
            "u9",
            "李四",
            "注意安全",
        )

    def test_empty_and_invalid(self):
        """空行 / 不合法输入返回 None。"""
        conn = RdfConnector("ws://x", on_danmaku=None)
        assert conn._parse_line("") is None
        assert conn._parse_line("   ") is None
        assert conn._parse_line("{not-json}") is None


# ================================================================ 工厂
class TestFactory:
    def test_none_returns_none(self):
        assert create_connector({"type": "none"}, on_danmaku=None) is None
        assert create_connector({}, on_danmaku=None) is None

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            create_connector({"type": "weird"}, on_danmaku=None)
        async def cb(u, un, t):
            pass
        with pytest.raises(ValueError):
            create_connector({"type": "nope"}, on_danmaku=cb)

    def test_rdf_returns_rdf(self):
        async def cb(u, un, t):
            pass
        conn = create_connector({"type": "rdf", "websocket_url": "ws://a:1"}, on_danmaku=cb)
        assert isinstance(conn, RdfConnector)
        assert conn.url == "ws://a:1"

    def test_rdf_default_url_from_host_port(self):
        conn = create_connector({"type": "rdf", "host": "1.2.3.4", "port": 9000})
        assert isinstance(conn, RdfConnector)
        assert conn.url == "ws://1.2.3.4:9000"

    def test_bilibili_returns_bilibili(self):
        conn = create_connector({"type": "bilibili", "room_id": "123"})
        assert isinstance(conn, BilibiliConnector)
        assert "room_id=123" in conn.url


# ================================================================ 生命周期
class _FakeConnector(DanmakuConnector):
    """不联网的假连接器：覆盖 _run 仅维持 running 循环。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.started = False
        self.stopped = False

    async def _run(self):
        self.started = True
        try:
            while self.running:
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            raise
        finally:
            self.running = False
            self.stopped = True


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        conn = _FakeConnector("ws://x")
        assert conn.running is False

        await conn.start()
        assert conn.running is True
        assert conn._task is not None
        await asyncio.sleep(0.02)
        assert conn.started is True

        # start 幂等：重复启动不新增 task
        await conn.start()
        assert conn.running is True

        await conn.stop()
        assert conn.running is False
        assert conn.stopped is True
        await asyncio.sleep(0.01)

        # stop 幂等：再次停止无副作用
        await conn.stop()

    @pytest.mark.asyncio
    async def test_callback_triggered(self):
        got = []

        async def cb(userid, username, text):
            got.append((userid, username, text))

        conn = _FakeConnector("ws://x", on_danmaku=cb)
        # 直接驱动调度层，不建真实连接
        await conn._dispatch("水友: 你好呀")
        await conn._dispatch('{"username": "张三", "msg": "晚上好"}')
        assert got == [("", "水友", "你好呀"), ("", "张三", "晚上好")]