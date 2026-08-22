"""CXFC relay → WebSocket 推送全链路测试（P2-T2）。

覆盖后端 relay dispatcher 经 WebSocketManager 广播 {type:"cxfc_relay_call"} 的装配与投递：
- 装配：enable_relay_ws_dispatch() 后，已注册/新注册 relay 插件自动注入真实 WS dispatcher；
        未装配时保持既有"显式注入"语义（回归兼容）
- 全链路：调用 relay 插件 → WS 收到 cxfc_relay_call（载荷完整）→ complete_relay_result 回报 →
          call_tool 返回结果
- 错误语义：无 WS 连接 → RELAY_UNREACHABLE；dispatcher 广播异常 → RELAY_UNREACHABLE；
            投递后无人回报 → RELAY_TIMEOUT

沿用 test_cxfc_transport.py 的 fake 依赖模式，mock WebSocketManager，不发起任何网络调用。

运行：python -m pytest tests/test_cxfc_relay_ws.py -q
"""
import asyncio

import pytest

from server.core.cxfc.manager import (
    CXFCManager,
    ERROR_RELAY_UNREACHABLE,
    ERROR_RELAY_TIMEOUT,
)


# ================================================================ fake 依赖
class FakeStorage:
    def __init__(self):
        self.plugins = {}

    async def init_db(self):
        pass

    async def load_plugins(self):
        return list(self.plugins.values())

    async def save_plugin(self, p):
        self.plugins[p.plugin_id] = p

    async def delete_plugin(self, pid):
        self.plugins.pop(pid, None)

    async def update_status(self, pid, status, last_seen=None):
        p = self.plugins.get(pid)
        if p:
            p.status = status

    async def close(self):
        pass


class FakeWsManager:
    """mock WebSocketManager：记录广播消息；connections 可空/非空。"""

    def __init__(self, connections=None):
        self.connections = connections if connections is not None else {}
        self.sent = []

    async def broadcast(self, message, exclude=None):
        self.sent.append(message)


@pytest.fixture
def manager():
    m = CXFCManager()
    m._storage = FakeStorage()
    yield m
    m._plugins_lock = asyncio.Lock()


# ================================================================ WS 装配
class TestRelayWsDispatchAssembly:
    @pytest.mark.asyncio
    async def test_enable_backfills_existing_relay_plugins(self, manager):
        """enable 后，已注册的 relay 插件自动获得真实 WS dispatcher。"""
        plugin = await manager.register_relay_plugin("existing", tools=[{"name": "t1"}])
        manager.set_ws_manager(FakeWsManager({"c1": object()}))
        manager.enable_relay_ws_dispatch()
        assert manager._dispatch_relay.get(plugin.plugin_id) is not None

    @pytest.mark.asyncio
    async def test_register_after_enable_auto_injects_dispatcher(self, manager):
        """enable 后新注册 relay 插件自动注入 dispatcher（无需显式 register_relay_dispatcher）。"""
        manager.set_ws_manager(FakeWsManager({"c1": object()}))
        manager.enable_relay_ws_dispatch()
        plugin = await manager.register_relay_plugin("new", tools=[{"name": "t1"}])
        assert manager._dispatch_relay.get(plugin.plugin_id) is not None

    @pytest.mark.asyncio
    async def test_without_enable_keeps_uninjected(self, manager):
        """未装配 WS dispatcher 时保持既有语义：relay 插件不自动注入通道（回归兼容）。"""
        plugin = await manager.register_relay_plugin("no-ws", tools=[{"name": "t1"}])
        assert manager._dispatch_relay.get(plugin.plugin_id) is None


# ================================================================ WS 全链路
class TestRelayWsRoundtrip:
    @pytest.mark.asyncio
    async def test_call_tool_relay_broadcasts_cxfc_relay_call(self, manager):
        """调用 relay 插件时，WS 收到 {type:"cxfc_relay_call",...} 且载荷完整；回报后返回结果。"""
        ws = FakeWsManager({"c1": object()})
        manager.set_ws_manager(ws)
        manager.enable_relay_ws_dispatch()
        plugin = await manager.register_relay_plugin(
            "ws1", name="前端承载", tools=[{"name": "t1"}], token="tok"
        )

        delivered = {}

        async def report():
            await asyncio.sleep(0.02)
            sent = next(m for m in ws.sent if m.get("type") == "cxfc_relay_call")
            delivered.update(sent)
            manager.complete_relay_result(
                plugin.plugin_id, sent["request_id"], {"success": True, "result": "ok"}
            )

        asyncio.create_task(report())
        result = await manager.call_tool(plugin.plugin_id, "t1", {"a": 1})

        assert result["success"] is True
        assert result["result"] == "ok"
        # WS 广播载荷：type/plugin_id/tool/arguments/request_id/token 完整
        assert delivered["type"] == "cxfc_relay_call"
        assert delivered["plugin_id"] == plugin.plugin_id
        assert delivered["tool"] == "t1"
        assert delivered["arguments"] == {"a": 1}
        assert delivered["request_id"]
        assert delivered["token"] == "tok"

    @pytest.mark.asyncio
    async def test_call_tool_relay_unreachable_without_connection(self, manager):
        """WS 无活跃连接 → RELAY_UNREACHABLE。"""
        manager.set_ws_manager(FakeWsManager())  # connections 为空
        manager.enable_relay_ws_dispatch()
        plugin = await manager.register_relay_plugin("ws2", tools=[{"name": "t1"}])
        result = await manager.call_tool(plugin.plugin_id, "t1", {})
        assert result["success"] is False
        assert ERROR_RELAY_UNREACHABLE in result["error"]

    @pytest.mark.asyncio
    async def test_call_tool_relay_dispatcher_exception_unreachable(self, manager):
        """dispatcher 广播抛异常 → 返回 False → RELAY_UNREACHABLE。"""

        class BoomWs(FakeWsManager):
            async def broadcast(self, message, exclude=None):
                raise RuntimeError("ws down")

        manager.set_ws_manager(BoomWs({"c1": object()}))
        manager.enable_relay_ws_dispatch()
        plugin = await manager.register_relay_plugin("ws4", tools=[{"name": "t1"}])
        result = await manager.call_tool(plugin.plugin_id, "t1", {})
        assert result["success"] is False
        assert ERROR_RELAY_UNREACHABLE in result["error"]

    @pytest.mark.asyncio
    async def test_call_tool_relay_timeout(self, manager):
        """有连接但前端不回报 → RELAY_TIMEOUT。"""
        manager._relay_timeout = 0.05
        manager.set_ws_manager(FakeWsManager({"c1": object()}))
        manager.enable_relay_ws_dispatch()
        plugin = await manager.register_relay_plugin("ws3", tools=[{"name": "t1"}])
        result = await manager.call_tool(plugin.plugin_id, "t1", {})
        assert result["success"] is False
        assert ERROR_RELAY_TIMEOUT in result["error"]
