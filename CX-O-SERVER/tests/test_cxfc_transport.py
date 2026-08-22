"""CXFC 多传输（transport）契约与分发测试。

覆盖 direct / relay / embedded 三种传输：
- 契约：transport 字段默认值、relay/embedded 载荷字段、错误码常量
- Embedded：进程内 handler 注册进 ToolRegistry、call_tool 进程内分发、handler 缺失错误码
- Relay：注册→注入通道→投递→回报全链路、无通道错误码、超时错误码、不直连 host:port
- direct 保持向后兼容：未声明 transport 按 direct 处理

运行：python -m pytest tests/test_cxfc_transport.py -v
"""
import asyncio
import types

import pytest

from server.core.cxfc.manager import (
    CXFCManager,
    ERROR_RELAY_UNREACHABLE,
    ERROR_RELAY_TIMEOUT,
    ERROR_EMBEDDED_HANDLER_MISSING,
)
from server.core.cxfc.models import (
    PluginStatus,
    PluginTransport,
    CXFCRegisterRequest,
    CXFCRelayRegisterRequest,
    CXFCRelayResultRequest,
    CXFCEmbeddedRegisterRequest,
)
from server.core.tools.registry import ToolRegistry


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


@pytest.fixture
def manager():
    m = CXFCManager()
    m._storage = FakeStorage()
    yield m
    m._plugins_lock = asyncio.Lock()


# ================================================================ 契约
class TestTransportContract:
    def test_transport_default_is_direct(self):
        req = CXFCRegisterRequest()
        assert req.transport == PluginTransport.DIRECT

    def test_relay_and_embedded_register_models(self):
        r = CXFCRelayRegisterRequest(name="fp", tools=[{"name": "t"}])
        assert r.transport == PluginTransport.RELAY
        e = CXFCEmbeddedRegisterRequest(plugin_id="eb")
        assert e.transport == PluginTransport.EMBEDDED

    def test_error_code_constants_defined(self):
        assert ERROR_RELAY_UNREACHABLE == "RELAY_UNREACHABLE"
        assert ERROR_RELAY_TIMEOUT == "RELAY_TIMEOUT"
        assert ERROR_EMBEDDED_HANDLER_MISSING == "EMBEDDED_HANDLER_MISSING"

    def test_cxfcinfo_accepts_empty_host_port(self):
        from server.core.cxfc.models import CXFCPluginInfo

        p = CXFCPluginInfo(plugin_id="embedded_x", transport=PluginTransport.EMBEDDED)
        assert p.host == ""
        assert p.port == 0


# ================================================================ Embedded
class TestEmbedded:
    @pytest.mark.asyncio
    async def test_register_embedded_registers_tool_with_handler(self, manager):
        registry = types.SimpleNamespace(register=lambda **kw: None)
        manager.set_tool_registry(registry)
        calls = []

        def fake_register(**kw):
            calls.append(kw)

        registry.register = fake_register
        plugin = await manager.register_embedded_plugin(
            plugin_id="eb1",
            name="嵌入式",
            tools=[{"name": "echo", "description": "d", "parameters": {}}],
            handlers={"echo": lambda x: f"echo-{x}"},
        )
        assert plugin.transport == PluginTransport.EMBEDDED
        assert plugin.host == ""
        assert plugin.port == 0
        assert plugin.plugin_id == "embedded_eb1"
        # handler 已写入 ToolRegistry 注册调用
        assert calls and calls[0]["name"] == "echo"
        assert calls[0]["function"] is not None

    @pytest.mark.asyncio
    async def test_call_tool_embedded_in_process(self, manager):
        await manager.register_embedded_plugin(
            plugin_id="eb2",
            name="嵌入式",
            tools=[{"name": "echo", "parameters": {}}],
            handlers={"echo": lambda x, y=1: {"sum": x + y}},
        )
        result = await manager.call_tool("embedded_eb2", "echo", {"x": 2})
        assert result["success"] is True
        assert result["result"] == {"sum": 3}
        # 不产生任何 HTTP 调用：断言 http client 未使用
        assert manager._http_client is None

    @pytest.mark.asyncio
    async def test_call_tool_embedded_missing_handler(self, manager):
        await manager.register_embedded_plugin(
            plugin_id="eb3",
            tools=[{"name": "echo", "parameters": {}}],
            handlers={},
        )
        result = await manager.call_tool("embedded_eb3", "echo", {})
        assert result["success"] is False
        assert ERROR_EMBEDDED_HANDLER_MISSING in result["error"]

    @pytest.mark.asyncio
    async def test_tool_registry_can_execute_embedded_directly(self, manager):
        tr = ToolRegistry()
        manager.set_tool_registry(tr)
        await manager.register_embedded_plugin(
            plugin_id="eb4",
            tools=[{"name": "up", "description": "d", "parameters": {}}],
            handlers={"up": lambda s="x": s.upper()},
        )
        out = tr.call_tool("up", {"s": "hi"})
        assert out["success"] is True
        assert out["result"] == "HI"


# ================================================================ Relay
class TestRelay:
    @pytest.mark.asyncio
    async def test_register_relay_plugin(self, manager):
        plugin = await manager.register_relay_plugin(
            plugin_id="fp1", name="前端承载", tools=[{"name": "t1"}], token="tok"
        )
        assert plugin.transport == PluginTransport.RELAY
        assert plugin.plugin_id == "relay_fp1"

    @pytest.mark.asyncio
    async def test_call_tool_relay_unreachable_without_channel(self, manager):
        await manager.register_relay_plugin("fp2", tools=[{"name": "t1"}])
        result = await manager.call_tool("relay_fp2", "t1", {})
        assert result["success"] is False
        assert ERROR_RELAY_UNREACHABLE in result["error"]

    @pytest.mark.asyncio
    async def test_call_tool_relay_full_roundtrip(self, manager):
        await manager.register_relay_plugin("fp3", tools=[{"name": "t1"}])
        # 注入通道：记录投递消息，返回连通
        delivered = {}

        def dispatcher(msg):
            delivered.update(msg)
            return True

        manager.register_relay_dispatcher("relay_fp3", dispatcher)
        # 在独立 task 中等待投递后回报结果
        async def report():
            await asyncio.sleep(0.02)
            manager.complete_relay_result(
                "relay_fp3", delivered["request_id"], {"success": True, "result": "ok"}
            )

        asyncio.create_task(report())
        result = await manager.call_tool("relay_fp3", "t1", {"a": 1})
        assert result["success"] is True
        assert result["result"] == "ok"
        # 确认是 relay 投递而非直连：消息含 tool/arguments/request_id
        assert delivered["tool"] == "t1"
        assert delivered["arguments"] == {"a": 1}
        assert delivered["request_id"]

    @pytest.mark.asyncio
    async def test_call_tool_relay_timeout(self, manager):
        manager._relay_timeout = 0.05
        await manager.register_relay_plugin("fp4", tools=[{"name": "t1"}])

        def dispatcher(msg):
            return True  # 永不回报 → 超时

        manager.register_relay_dispatcher("relay_fp4", dispatcher)
        result = await manager.call_tool("relay_fp4", "t1", {})
        assert result["success"] is False
        assert ERROR_RELAY_TIMEOUT in result["error"]

    @pytest.mark.asyncio
    async def test_relay_targets_lists_injected(self, manager):
        await manager.register_relay_plugin("fp5", name="目标")
        manager.register_relay_dispatcher("relay_fp5", lambda msg: True)
        targets = manager.get_relay_targets()
        assert any(t["plugin_id"] == "relay_fp5" and t["active"] for t in targets)


# ================================================================ direct 兼容
class TestDirectCompatibility:
    @pytest.mark.asyncio
    async def test_register_request_default_transport_is_direct(self, manager):
        req = CXFCRegisterRequest(host="h", port=1)
        plugin = await manager.register_plugin(req)
        assert plugin.transport == PluginTransport.DIRECT
        assert plugin.plugin_id == "cxfc_h_1"

    @pytest.mark.asyncio
    async def test_relay_result_models(self):
        r = CXFCRelayResultRequest(plugin_id="p", request_id="r1", success=True, result="v")
        assert r.result == "v"
        assert r.error is None