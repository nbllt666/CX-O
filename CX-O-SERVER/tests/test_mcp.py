"""server.core.tools.mcp 单元测试。

覆盖 MCP 管理器：MCPServer 数据类（默认/自定义端点、to_dict）、服务器增删、
启动（命令/参数注入校验、进程启动、失败检测）、停止、健康检查、工具同步
（HTTP 200/非 200/连接异常）、工具调用（成功/服务器缺失/未连接/HTTP/超时/
连接异常）、统计与关闭。subprocess.Popen、httpx.AsyncClient、asyncio.sleep
均以替身隔离，避免真实进程与网络。

运行：python -m pytest tests/test_mcp.py -v
"""
import asyncio

import pytest

import server.core.tools.mcp as mcp
from server.core.exceptions import MCPError


class FakeProcess:
    def __init__(self, pid=123, poll_result=None, stdout_cmds=(), stderr_bytes=b""):
        self.pid = pid
        self._poll = poll_result
        self.stdout = iter([b"out-line"])
        self.stderr = iter([b"err-line"])
        self.stderr_cmds = stderr_bytes
        self.terminated = False
        self.wait_called = False
        self.communicate_called = False

    def poll(self):
        return self._poll

    def communicate(self):
        self.communicate_called = True
        return b"", self.stderr_cmds

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.wait_called = True
        return 0


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self):
        return self._json


class FakeClient:
    def __init__(self, get_response=None, post_response=None, get_exc=None, post_exc=None):
        self.get_response = get_response or FakeResponse(200, {"tools": []})
        self.post_response = post_response or FakeResponse(200, {"ok": True})
        self.get_exc = get_exc
        self.post_exc = post_exc
        self.closed = False
        self.get_urls = []
        self.post_calls = []

    async def get(self, url, timeout=None):
        self.get_urls.append(url)
        if self.get_exc:
            raise self.get_exc
        return self.get_response

    async def post(self, url, json=None):
        self.post_calls.append((url, json))
        if self.post_exc:
            raise self.post_exc
        return self.post_response

    async def aclose(self):
        self.closed = True


class FakeRegistry:
    def __init__(self):
        self.registrations = []

    def register(self, **kwargs):
        self.registrations.append(kwargs)


@pytest.fixture
def mgr():
    return mcp.MCPManager()


# ---------------------------------------------------------------- MCPServer
class TestMCPServer:
    def test_default_endpoint(self):
        s = mcp.MCPServer(name="a", command="cmd", args=[], env={})
        assert s.endpoint_url == "http://localhost:8600"
        assert s.status == "disconnected"

    def test_custom_endpoint(self):
        s = mcp.MCPServer(name="a", command="cmd", args=[], env={}, endpoint_url="http://x:1")
        assert s.endpoint_url == "http://x:1"

    def test_to_dict(self):
        s = mcp.MCPServer(name="a", command="cmd", args=["a"], env={"K": "V"}, tools=[{"t": 1}])
        d = s.to_dict()
        assert d["name"] == "a"
        assert d["tools"] == [{"t": 1}]
        assert d["status"] == "disconnected"


# ---------------------------------------------------------------- 增删
class TestAddRemove:
    @pytest.mark.asyncio
    async def test_add_server(self, mgr):
        d = await mgr.add_server("s1", "cmd", ["a"], env={"K": "V"}, endpoint_url="http://e:80")
        assert d["name"] == "s1"
        assert d["endpoint_url"] == "http://e:80"
        assert "s1" in mgr.servers

    @pytest.mark.asyncio
    async def test_remove_server(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        assert await mgr.remove_server("s1") is True
        assert "s1" not in mgr.servers

    @pytest.mark.asyncio
    async def test_remove_missing(self, mgr):
        assert await mgr.remove_server("nope") is False

    @pytest.mark.asyncio
    async def test_remove_terminates_process(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        proc = FakeProcess()
        mgr.servers["s1"].process = proc
        mgr._http_clients["s1"] = FakeClient()
        assert await mgr.remove_server("s1") is True
        assert proc.terminated is True
        assert "s1" not in mgr._http_clients


# ---------------------------------------------------------------- 启动
class TestStartServer:
    @pytest.mark.asyncio
    async def test_missing_server(self, mgr):
        with pytest.raises(MCPError):
            await mgr.start_server("nope")

    @pytest.mark.asyncio
    async def test_already_connected(self, mgr, monkeypatch):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].status = "connected"
        monkeypatch.setattr("server.core.tools.mcp.subprocess.Popen", lambda *a, **k: FakeProcess())
        monkeypatch.setattr("server.core.tools.mcp.asyncio.sleep", lambda *a: asyncio.sleep(0))
        assert await mgr.start_server("s1") is True
        assert mgr.servers["s1"].process is None  # 未重新启动

    @pytest.mark.asyncio
    async def test_invalid_command(self, mgr):
        await mgr.add_server("s1", "", [])
        with pytest.raises(MCPError):
            await mgr.start_server("s1")

    @pytest.mark.asyncio
    async def test_dangerous_command(self, mgr):
        await mgr.add_server("s1", "cmd;rm -rf", [])
        with pytest.raises(MCPError):
            await mgr.start_server("s1")

    @pytest.mark.asyncio
    async def test_args_not_list(self, mgr):
        await mgr.add_server("s1", "cmd", "notalist")
        with pytest.raises(MCPError):
            await mgr.start_server("s1")

    @pytest.mark.asyncio
    async def test_dangerous_arg(self, mgr):
        await mgr.add_server("s1", "cmd", ["ok", "bad|pipe"])
        with pytest.raises(MCPError):
            await mgr.start_server("s1")

    @pytest.mark.asyncio
    async def test_start_success(self, mgr, monkeypatch):
        proc = FakeProcess(poll_result=None)
        monkeypatch.setattr("server.core.tools.mcp.subprocess.Popen", lambda *a, **k: proc)

        async def _noop_sleep(*a):
            return None

        monkeypatch.setattr("server.core.tools.mcp.asyncio.sleep", _noop_sleep)
        await mgr.add_server("s1", "cmd", ["a"])
        # 覆盖 _sync_tools 避免真实 HTTP
        calls = {}

        async def fake_sync(self, name):
            calls["name"] = name

        monkeypatch.setattr(mcp.MCPManager, "_sync_tools", fake_sync)
        assert await mgr.start_server("s1") is True
        assert mgr.servers["s1"].status == "connected"
        assert proc.terminated is False
        assert calls.get("name") == "s1"

    @pytest.mark.asyncio
    async def test_start_process_dies(self, mgr, monkeypatch):
        proc = FakeProcess(poll_result=1, stderr_bytes=b"boot fail")
        monkeypatch.setattr("server.core.tools.mcp.subprocess.Popen", lambda *a, **k: proc)

        async def _noop_sleep(*a):
            return None

        monkeypatch.setattr("server.core.tools.mcp.asyncio.sleep", _noop_sleep)
        await mgr.add_server("s1", "cmd", [])
        with pytest.raises(MCPError):
            await mgr.start_server("s1")
        assert mgr.servers["s1"].status == "error"


# ---------------------------------------------------------------- 停止/健康
class TestStopHealth:
    @pytest.mark.asyncio
    async def test_stop_missing(self, mgr):
        with pytest.raises(MCPError):
            await mgr.stop_server("nope")

    @pytest.mark.asyncio
    async def test_stop_success(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].process = FakeProcess()
        assert await mgr.stop_server("s1") is True
        assert mgr.servers["s1"].status == "disconnected"

    @pytest.mark.asyncio
    async def test_stop_no_process(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        assert await mgr.stop_server("s1") is False

    @pytest.mark.asyncio
    async def test_health_missing(self, mgr):
        with pytest.raises(MCPError):
            await mgr.check_server_health("nope")

    @pytest.mark.asyncio
    async def test_health_running(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].process = FakeProcess(poll_result=None)
        r = await mgr.check_server_health("s1")
        assert r["status"] == "connected"

    @pytest.mark.asyncio
    async def test_health_dead(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].process = FakeProcess(poll_result=1)
        r = await mgr.check_server_health("s1")
        assert r["status"] == "disconnected"
        assert "退出" in r["error"]


# ---------------------------------------------------------------- 工具同步
class TestSyncTools:
    @pytest.mark.asyncio
    async def test_missing_server(self, mgr):
        await mgr._sync_tools("nope")  # 不抛异常

    @pytest.mark.asyncio
    async def test_sync_ok_registers(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr._tool_registry = FakeRegistry()
        mgr._http_clients["s1"] = FakeClient(
            get_response=FakeResponse(200, {"tools": [{"name": "t1", "description": "d", "parameters": {"p": 1}}]})
        )
        await mgr._sync_tools("s1")
        assert mgr.servers["s1"].tools == [{"name": "t1", "description": "d", "parameters": {"p": 1}}]
        assert mgr._tool_registry.registrations[0]["name"] == "t1"
        assert mgr._tool_registry.registrations[0]["category"] == "mcp"
        assert mgr._tool_registry.registrations[0]["tags"] == ["s1"]

    @pytest.mark.asyncio
    async def test_sync_non_200(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr._http_clients["s1"] = FakeClient(get_response=FakeResponse(500, None, text="boom"))
        await mgr._sync_tools("s1")
        assert "HTTP 500" in mgr.servers["s1"].error

    @pytest.mark.asyncio
    async def test_sync_connect_error(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr._http_clients["s1"] = FakeClient(get_exc=__import__("httpx").ConnectError("conn"))
        await mgr._sync_tools("s1")
        assert "无法连接" in mgr.servers["s1"].error


# ---------------------------------------------------------------- 调用/列表/统计
class TestCallTool:
    @pytest.mark.asyncio
    async def test_missing_server(self, mgr):
        r = await mgr.call_tool("nope", "t")
        assert r["success"] is False

    @pytest.mark.asyncio
    async def test_not_connected(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        r = await mgr.call_tool("s1", "t")
        assert r["success"] is False
        assert "未连接" in r["error"]

    @pytest.mark.asyncio
    async def test_call_success(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].status = "connected"
        mgr._http_clients["s1"] = FakeClient(post_response=FakeResponse(200, {"ok": 1}))
        r = await mgr.call_tool("s1", "t", {"a": 1})
        assert r["success"] is True
        assert r["result"] == {"ok": 1}
        assert mgr._http_clients["s1"].post_calls[0][1] == {"tool": "t", "arguments": {"a": 1}}

    @pytest.mark.asyncio
    async def test_call_http_error(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].status = "connected"
        mgr._http_clients["s1"] = FakeClient(post_response=FakeResponse(500, None, text="err"))
        r = await mgr.call_tool("s1", "t")
        assert r["success"] is False
        assert "HTTP 500" in r["error"]

    @pytest.mark.asyncio
    async def test_call_timeout(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].status = "connected"
        mgr._http_clients["s1"] = FakeClient(post_exc=__import__("httpx").TimeoutException("t"))
        r = await mgr.call_tool("s1", "t")
        assert r["success"] is False
        assert "超时" in r["error"]

    @pytest.mark.asyncio
    async def test_call_connect_error(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].status = "connected"
        mgr._http_clients["s1"] = FakeClient(post_exc=__import__("httpx").ConnectError("c"))
        r = await mgr.call_tool("s1", "t")
        assert r["success"] is False
        assert "无法连接" in r["error"]


class TestListStatsClose:
    @pytest.mark.asyncio
    async def test_list_servers(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        await mgr.add_server("s2", "cmd", [])
        assert len(await mgr.list_servers()) == 2

    @pytest.mark.asyncio
    async def test_get_tools(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].tools = [{"name": "t1"}]
        assert await mgr.get_tools("s1") == [{"name": "t1"}]

    @pytest.mark.asyncio
    async def test_get_tools_missing(self, mgr):
        assert await mgr.get_tools("nope") == []

    def test_get_stats(self, mgr):
        s1 = mcp.MCPServer(name="s1", command="c", args=[], env={}, status="connected")
        s2 = mcp.MCPServer(name="s2", command="c", args=[], env={}, status="disconnected")
        s3 = mcp.MCPServer(name="s3", command="c", args=[], env={}, status="error")
        mgr.servers = {"s1": s1, "s2": s2, "s3": s3}
        st = mgr.get_stats()
        assert st["total_servers"] == 3
        assert st["connected_servers"] == 1
        assert st["disconnected_servers"] == 1
        assert st["error_servers"] == 1

    @pytest.mark.asyncio
    async def test_close(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        client = FakeClient()
        mgr._http_clients["s1"] = client
        mgr.servers["s1"].process = FakeProcess()
        await mgr.close()
        assert client.closed is True
        assert mgr._http_clients == {}
        assert mgr.servers == {}


# ---------------------------------------------------------------- 幽灵工具清理 / close 非阻塞
class _FakeTool:
    def __init__(self, name, category, tags):
        self.name = name
        self.category = category
        self.tags = tags


class RegistryWithDelete(FakeRegistry):
    """带 list_tools/delete_tool 的注册表替身（记录注销调用）。"""

    def __init__(self):
        super().__init__()
        self._tools = {}
        self.deleted = []

    def register(self, **kwargs):
        super().register(**kwargs)
        self._tools[kwargs["name"]] = _FakeTool(
            kwargs["name"], kwargs.get("category", "general"), list(kwargs.get("tags") or [])
        )

    def list_tools(self, enabled_only=True, include_builtin=False):
        return list(self._tools.values())

    def delete_tool(self, name):
        if name in self._tools:
            del self._tools[name]
            self.deleted.append(name)
            return True
        return False


class TestGhostToolCleanup:
    @pytest.mark.asyncio
    async def test_remove_server_unregisters_ghost_tools(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        reg = RegistryWithDelete()
        mgr.set_tool_registry(reg)
        reg.register(name="t_keep", description="", parameters={}, category="general", tags=[])
        reg.register(name="t_s1", description="", parameters={}, category="mcp", tags=["s1"])
        reg.register(name="t_s2", description="", parameters={}, category="mcp", tags=["s2"])
        assert await mgr.remove_server("s1") is True
        # 仅注销本 server 的幽灵工具，其余不动
        assert reg.deleted == ["t_s1"]
        remaining = {t.name for t in reg.list_tools()}
        assert remaining == {"t_keep", "t_s2"}

    @pytest.mark.asyncio
    async def test_stop_server_unregisters_ghost_tools(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        mgr.servers["s1"].process = FakeProcess()
        reg = RegistryWithDelete()
        mgr.set_tool_registry(reg)
        reg.register(name="t_keep", description="", parameters={}, category="mcp", tags=["other"])
        reg.register(name="t_s1", description="", parameters={}, category="mcp", tags=["s1"])
        assert await mgr.stop_server("s1") is True
        assert reg.deleted == ["t_s1"]

    @pytest.mark.asyncio
    async def test_close_terminates_and_waits_process(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        proc = FakeProcess()
        mgr.servers["s1"].process = proc
        await mgr.close()
        assert proc.terminated is True
        assert proc.wait_called is True


# ---------------------------------------------------------------- 工具同步零校验修复
class TestSyncToolsValidation:
    async def _sync(self, mgr, server_name, tools_payload):
        mgr.servers[server_name].status = "connected"  # 不参与 _sync_tools，但保持语义清晰
        mgr._http_clients[server_name] = FakeClient(
            get_response=FakeResponse(200, {"tools": tools_payload})
        )
        await mgr._sync_tools(server_name)

    @pytest.mark.asyncio
    async def test_skips_invalid_name(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        reg = FakeRegistry()
        mgr._tool_registry = reg
        await self._sync(mgr, "s1", [
            {"name": "", "description": "d", "parameters": {}},
            {"description": "无 name 字段"},
            {"name": 123, "description": "name 非字符串"},
        ])
        assert reg.registrations == []

    @pytest.mark.asyncio
    async def test_skips_non_dict_parameters(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        reg = FakeRegistry()
        mgr._tool_registry = reg
        await self._sync(mgr, "s1", [
            {"name": "ok1", "description": "d", "parameters": "not-a-dict"},
        ])
        assert reg.registrations == []

    @pytest.mark.asyncio
    async def test_skips_non_object_parameter_type(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        reg = FakeRegistry()
        mgr._tool_registry = reg
        await self._sync(mgr, "s1", [
            {"name": "bad", "description": "d", "parameters": {"type": "string"}},
        ])
        assert reg.registrations == []

    @pytest.mark.asyncio
    async def test_accepts_object_type_and_missing_type(self, mgr):
        await mgr.add_server("s1", "cmd", [])
        reg = FakeRegistry()
        mgr._tool_registry = reg
        await self._sync(mgr, "s1", [
            {"name": "typed", "description": "d", "parameters": {"type": "object", "properties": {}}},
            {"name": "legacy", "description": "d", "parameters": {"p": 1}},
        ])
        assert [r["name"] for r in reg.registrations] == ["typed", "legacy"]