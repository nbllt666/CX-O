"""server.core.cxfc（CXFCManager + CXFCDiscovery）单元测试。

通过注入轻量 fake storage / fake http client / fake socket，隔离真实 SQLite、
网络 IO，覆盖 CXFCManager 的管理逻辑与 CXFCDiscovery 的发现生命周期：

- Manager: 注册/连接/断开/调工具/心跳/事件推送/插件查询/关闭
- Discovery: 启动/停止/扫描/广播/已发现列表

运行：python -m pytest tests/test_cxfc_manager.py -v
"""
import asyncio
import json
import types

import pytest

from server.core.cxfc.manager import CXFCManager
from server.core.cxfc.discovery import CXFCDiscovery
from server.core.cxfc.models import (
    PluginStatus,
    CXFCEvent,
    CXFCRegisterRequest,
)


# ================================================================ fake 依赖
class FakeStorage:
    """内存版 storage，模拟 init_db/load/save/update_status/delete/close。"""

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
            if last_seen:
                p.last_seen = last_seen

    async def close(self):
        pass


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


class FakeHttpClient:
    """按 (method, url) 返回预设响应的假客户端。"""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.closed = False

    async def get(self, url, timeout=5.0):
        return self._route("get", url)

    async def post(self, url, json=None, headers=None, timeout=30.0):
        self.last_headers = headers
        return self._route("post", url)

    def _route(self, method, url):
        for key, resp in self.routes.items():
            if key == (method, url):
                return resp
        return FakeResponse(404, {})

    async def aclose(self):
        self.closed = True


@pytest.fixture
def manager():
    m = CXFCManager()
    m._storage = FakeStorage()
    m._http_client = FakeHttpClient()
    yield m
    # 关闭锁游标，避免 asyncio.Lock 在事件循环间复用告警
    m._plugins_lock = asyncio.Lock()


def _plugin(pid="p1", host="127.0.0.1", port=8000, **kw):
    defaults = dict(
        plugin_id=pid, host=host, port=port,
        status=PluginStatus.CONNECTED, tools=[{"name": "t1"}],
    )
    defaults.update(kw)
    return CXFCPluginInfo(**defaults)


# ================================================================ Manager
class TestManagerRegister:
    @pytest.mark.asyncio
    async def test_register_plugin_adds_and_persists(self, manager):
        req = CXFCRegisterRequest(
            host="127.0.0.1", port=8000, name="插件A",
            tools=[{"name": "t", "description": "d"}],
            skills=[{"name": "s", "auto_inject": False}],
        )
        p = await manager.register_plugin(req)
        assert p.plugin_id == "cxfc_127.0.0.1_8000"
        assert manager.get_plugin(p.plugin_id) is p
        assert p.plugin_id in manager._storage.plugins
        # skill 已注册
        assert [s.name for s in manager.get_skill_registry().get_all_skills()] == ["s"]

    @pytest.mark.asyncio
    async def test_register_plugin_registers_tools(self, manager):
        calls = []
        registry = types.SimpleNamespace(register=lambda **kw: calls.append(kw))
        manager.set_tool_registry(registry)
        req = CXFCRegisterRequest(host="h", port=1, tools=[{"name": "t2"}])
        await manager.register_plugin(req)
        assert calls and calls[0]["name"] == "t2"
        assert calls[0]["category"] == "cxfc"


class TestManagerConnect:
    @pytest.mark.asyncio
    async def test_connect_alive_success(self, manager):
        manager._http_client.routes = {
            ("get", "http://127.0.0.1:8080/health"): FakeResponse(
                200, {"name": "P", "version": "2.0"}
            ),
            ("get", "http://127.0.0.1:8080/tools"): FakeResponse(200, {"tools": []}),
            ("get", "http://127.0.0.1:8080/skills"): FakeResponse(200, {"skills": []}),
        }
        p = await manager.connect_to_plugin("127.0.0.1", 8080)
        assert p is not None
        assert p.name == "P"
        assert p.status == PluginStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_connect_not_alive_returns_none(self, manager):
        manager._http_client.routes = {
            ("get", "http://127.0.0.1:9/health"): FakeResponse(503)
        }
        assert await manager.connect_to_plugin("127.0.0.1", 9) is None

    @pytest.mark.asyncio
    async def test_check_alive_success_failure(self, manager):
        manager._http_client.routes = {
            ("get", "http://h:1/health"): FakeResponse(200),
            ("get", "http://h:2/health"): FakeResponse(500),
        }
        assert await manager._check_alive("h", 1) is True
        assert await manager._check_alive("h", 2) is False


class TestManagerDisconnect:
    @pytest.mark.asyncio
    async def test_disconnect_removes_and_persists(self, manager):
        await manager.register_plugin(CXFCRegisterRequest(host="h", port=1))
        await manager.disconnect_plugin("cxfc_h_1")
        assert manager.get_plugin("cxfc_h_1") is None
        assert "cxfc_h_1" not in manager._storage.plugins

    @pytest.mark.asyncio
    async def test_disconnect_missing_is_noop(self, manager):
        await manager.disconnect_plugin("nope")  # 不应抛异常


class TestManagerCallTool:
    @pytest.mark.asyncio
    async def test_call_tool_success(self, manager):
        await manager.register_plugin(CXFCRegisterRequest(host="h", port=1))
        manager._http_client.routes = {
            ("post", "http://h:1/call"): FakeResponse(200, {"success": True})
        }
        out = await manager.call_tool("cxfc_h_1", "t1", {"a": 1})
        assert out == {"success": True}

    @pytest.mark.asyncio
    async def test_call_tool_unavailable_plugin(self, manager):
        out = await manager.call_tool("missing", "t")
        assert out["success"] is False


class TestManagerHeartbeat:
    @pytest.mark.asyncio
    async def test_update_heartbeat_reconnects(self, manager):
        await manager.register_plugin(CXFCRegisterRequest(host="h", port=1))
        pid = "cxfc_h_1"
        manager._storage.plugins[pid].status = PluginStatus.DISCONNECTED
        ok = await manager.update_heartbeat(pid, 1)
        assert ok is True
        assert manager.get_plugin(pid).status == PluginStatus.CONNECTED

    @pytest.mark.asyncio
    async def test_update_heartbeat_unknown_returns_false(self, manager):
        assert await manager.update_heartbeat("nope", 1) is False


class TestManagerEvent:
    @pytest.mark.asyncio
    async def test_push_event_invokes_callback(self, manager):
        await manager.register_plugin(CXFCRegisterRequest(host="h", port=1))
        # 注册一个事件型 skill
        manager.get_skill_registry().register_skill(
            types.SimpleNamespace(
                name="on_x", source_plugin_id="cxfc_h_1",
                description="", prompt_template="",
                trigger_keywords=[], trigger_events=["x"], auto_inject=True,
            )
        )
        fired = []
        manager.set_on_event_callback(
            lambda skill, event: fired.append((skill.name, event.from_port))
        )
        evt = CXFCEvent(from_port=1, event_type="x", data={"title": "t"})
        ok = await manager.push_event(evt)
        assert ok is True
        assert fired == [("on_x", 1)]


class TestManagerShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_closes_client(self, manager):
        manager._http_client = FakeHttpClient()
        await manager.shutdown()
        assert manager._http_client.closed is True


# ================================================================ Discovery
class TestDiscovery:
    def test_get_discovered_initial_empty(self):
        assert CXFCDiscovery().get_discovered() == []

    @pytest.mark.asyncio
    async def test_stop_discovery_idempotent(self):
        d = CXFCDiscovery()
        await d.stop_discovery()
        assert d._running is False
        # 二次停止也应安全
        await d.stop_discovery()

    @pytest.mark.asyncio
    async def test_start_stop_with_fake_socket(self, monkeypatch):
        d = CXFCDiscovery()
        monkeypatch.setattr(d, "_broadcast_presence", _noop)
        monkeypatch.setattr(d, "_scan_network", _noop)
        await d.start_discovery(local_name="CX-O", local_port=8000)
        assert d._running is True
        await d.stop_discovery()
        assert d._running is False

    def test_scan_network_parses_beacons(self, monkeypatch):
        d = CXFCDiscovery()
        fake_sock = FakeDiscoverySocket(
            [json.dumps({"type": "CXFC_BEACON", "port": 9000, "name": "B"}).encode()]
        )
        d._discovery_socket = fake_sock
        asyncio.run(d._scan_network())
        found = d.get_discovered()
        assert found and found[0]["port"] == 9000

    def test_broadcast_presence_sends_beacon(self, monkeypatch):
        d = CXFCDiscovery()
        sent = []
        fake_sock = types.SimpleNamespace(sendto=lambda data, addr: sent.append((data, addr)))
        d._broadcast_socket = fake_sock
        asyncio.run(d._broadcast_presence("N", 8000, ["cap1"]))
        assert len(sent) == 1
        payload = json.loads(sent[0][0].decode())
        assert payload["type"] == "CXFC_BEACON"
        assert payload["port"] == 8000

    # ---------------------------------------------------------- L13 泄漏兜底
    class _LeakProbeSocket:
        """记录 close 调用的真实 socket 替身（含 bind 失败路径）。"""

        def __init__(self, *, bind_error=False, datagrams=()):
            self._bind_error = bind_error
            self._queue = list(datagrams)
            self.closed = False
            self.bound = None

        def setsockopt(self, *a):
            pass

        def settimeout(self, *a):
            pass

        def bind(self, addr):
            self.bound = addr
            if self._bind_error:
                raise OSError("addr in use")

        def recvfrom(self, bufsize):
            if self._queue:
                return self._queue.pop(0), ("127.0.0.1", 9996)
            import socket as _s

            raise _s.timeout()

        def close(self):
            self.closed = True

    @pytest.mark.asyncio
    async def test_public_scan_network_closes_socket_on_success(
        self, monkeypatch
    ):
        """L13 定向: 公共 scan_network 成功路径关闭临时 socket。"""
        import socket as socket_mod

        from server.core.cxfc import discovery as discovery_mod

        d = CXFCDiscovery(discovery_port=59996)
        probe = self._LeakProbeSocket(
            datagrams=[json.dumps({"type": "CXFC_BEACON", "port": 9100}).encode()]
        )
        monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: probe)
        # discovery 模块内 `import socket` 绑定同一模块对象 → patch 生效
        monkeypatch.setattr(discovery_mod.socket, "AF_INET", socket_mod.AF_INET)
        monkeypatch.setattr(discovery_mod.socket, "SOCK_DGRAM", socket_mod.SOCK_DGRAM)

        found = await d.scan_network()

        assert found and found[0]["port"] == 9100
        assert probe.closed is True

    @pytest.mark.asyncio
    async def test_public_scan_network_closes_socket_on_bind_failure(self, monkeypatch):
        """L13 定向: bind 抛 OSError 的异常路径同样 try/finally 兜底关闭。"""
        import socket as socket_mod

        from server.core.cxfc import discovery as discovery_mod

        d = CXFCDiscovery(discovery_port=59997)
        probe = self._LeakProbeSocket(bind_error=True)
        monkeypatch.setattr(socket_mod, "socket", lambda *a, **k: probe)
        monkeypatch.setattr(discovery_mod.socket, "AF_INET", socket_mod.AF_INET)
        monkeypatch.setattr(discovery_mod.socket, "SOCK_DGRAM", socket_mod.SOCK_DGRAM)

        with pytest.raises(OSError):
            await d.scan_network()

        assert probe.closed is True


class FakeDiscoverySocket:
    """模拟 discovery socket：缓存待收数据，抛 BlockingIOError 表示无更多数据。"""

    def __init__(self, datagrams):
        self._queue = list(datagrams)
        self._addr = ("127.0.0.1", 9996)

    def setblocking(self, flag):
        pass

    def recvfrom(self, bufsize):
        if self._queue:
            return self._queue.pop(0), self._addr
        raise BlockingIOError


async def _noop(*a, **k):
    pass