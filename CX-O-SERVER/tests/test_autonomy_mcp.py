"""P2-T1: MCP 工具源配置化注册/自启 + 自主搜索接入测试。

覆盖：
① config 默认 mcp_servers 为空列表
② MCPServerConfig 字段校验（默认值 / name 必填 / 完整字段）
③ 启动装配：enabled server 调 add_server+start_server、disabled 不启动（mock MCPManager）
④ 单个 server 启动失败不阻断其余
⑤ autonomy search_provider 注入：有 mcp 搜索工具时调用 tool_registry.call_tool、
   无工具/调用失败时返回 None 触发 HotspotMonitor 降级（mock tool_registry）

运行：python -m pytest tests/test_autonomy_mcp.py -q
"""
import pytest
from pydantic import ValidationError

from server.config import MCPServerConfig, UnifiedConfig
from server.core.tools.mcp import start_configured_servers
from server.autonomy.main import (
    _build_mcp_search_provider,
    _find_mcp_search_tool,
    _normalize_search_results,
    get_handlers,
    setup_autonomy,
)
from server.autonomy.perception.social.hotspot_monitor import HotspotMonitor


# ================================================================ ① config 默认
class TestConfigDefaults:
    def test_mcp_servers_default_empty(self):
        cfg = UnifiedConfig()
        assert cfg.mcp_servers == []

    def test_mcp_servers_load_from_dict(self):
        cfg = UnifiedConfig.model_validate(
            {"mcp_servers": [{"name": "free-search-mcp"}, {"name": "other", "enabled": False}]}
        )
        assert len(cfg.mcp_servers) == 2
        assert cfg.mcp_servers[0].name == "free-search-mcp"
        assert cfg.mcp_servers[0].enabled is True
        assert cfg.mcp_servers[1].enabled is False


# ================================================================ ② MCPServerConfig 校验
class TestMCPServerConfig:
    def test_defaults(self):
        s = MCPServerConfig(name="s1")
        assert s.name == "s1"
        assert s.command == ""
        assert s.args == []
        assert s.env == {}
        assert s.endpoint_url == "http://localhost:8600"
        assert s.enabled is True

    def test_name_required(self):
        with pytest.raises(ValidationError):
            MCPServerConfig(command="npx")

    def test_full_fields(self):
        s = MCPServerConfig(
            name="s1",
            command="npx",
            args=["-y", "free-search-mcp"],
            env={"KEY": "VALUE"},
            endpoint_url="http://127.0.0.1:9999",
            enabled=False,
        )
        assert s.command == "npx"
        assert s.args == ["-y", "free-search-mcp"]
        assert s.env == {"KEY": "VALUE"}
        assert s.endpoint_url == "http://127.0.0.1:9999"
        assert s.enabled is False


# ================================================================ ③④ 启动装配（mock MCPManager）
class RecordingMCPManager:
    """记录 add_server/start_server/_sync_tools 调用的 mock 管理器，可注入启动失败。"""

    def __init__(self):
        self.added = []
        self.started = []
        self.synced = []
        self.fail_start = set()
        self.fail_add = set()

    async def add_server(self, name, command="", args=None, env=None, endpoint_url=None):
        if name in self.fail_add:
            raise RuntimeError(f"add fail: {name}")
        self.added.append(
            {"name": name, "command": command, "args": args, "env": env, "endpoint_url": endpoint_url}
        )

    async def start_server(self, name):
        if name in self.fail_start:
            raise RuntimeError(f"start fail: {name}")
        self.started.append(name)

    async def _sync_tools(self, name):
        self.synced.append(name)


class TestConfiguredStartup:
    @pytest.mark.asyncio
    async def test_enabled_started_disabled_skipped(self):
        mgr = RecordingMCPManager()
        configs = [
            MCPServerConfig(name="search-server", command="npx", args=["-y", "mcp"]),
            MCPServerConfig(name="disabled-server", command="npx", enabled=False),
        ]
        await start_configured_servers(mgr, configs)
        # 只有 enabled 的 server 被 add + start + sync
        assert [a["name"] for a in mgr.added] == ["search-server"]
        assert mgr.started == ["search-server"]
        assert mgr.synced == ["search-server"]
        assert mgr.added[0]["command"] == "npx"
        assert mgr.added[0]["args"] == ["-y", "mcp"]
        assert mgr.added[0]["endpoint_url"] == "http://localhost:8600"

    @pytest.mark.asyncio
    async def test_single_start_failure_does_not_block_others(self):
        mgr = RecordingMCPManager()
        mgr.fail_start = {"bad-server"}
        configs = [
            MCPServerConfig(name="bad-server", command="boom"),
            MCPServerConfig(name="good-server", command="npx"),
        ]
        await start_configured_servers(mgr, configs)
        # 两个都被 add；bad 启动失败被隔离，good 正常启动 + sync
        assert [a["name"] for a in mgr.added] == ["bad-server", "good-server"]
        assert mgr.started == ["good-server"]
        assert mgr.synced == ["good-server"]

    @pytest.mark.asyncio
    async def test_single_add_failure_does_not_block_others(self):
        mgr = RecordingMCPManager()
        mgr.fail_add = {"bad-server"}
        configs = [
            MCPServerConfig(name="bad-server", command="boom"),
            MCPServerConfig(name="good-server", command="npx"),
        ]
        await start_configured_servers(mgr, configs)
        assert [a["name"] for a in mgr.added] == ["good-server"]
        assert mgr.started == ["good-server"]

    @pytest.mark.asyncio
    async def test_empty_configs_is_noop(self):
        mgr = RecordingMCPManager()
        await start_configured_servers(mgr, [])
        assert mgr.added == []
        assert mgr.started == []


# ================================================================ ⑤ search_provider 注入
class FakeTool:
    def __init__(self, name, category="mcp", enabled=True):
        self.name = name
        self.category = category
        self.enabled = enabled


class FakeRegistry:
    def __init__(self, tools=None, call_result=None, raise_on_call=False):
        self.tools = tools or []
        self.call_result = call_result or {
            "success": True,
            "result": [{"title": "标题", "link": "http://x", "snippet": "摘要"}],
        }
        self.raise_on_call = raise_on_call
        self.calls = []

    def list_tools(self, enabled_only=True, include_builtin=False):
        return [t for t in self.tools if (not enabled_only or t.enabled)]

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if self.raise_on_call:
            raise RuntimeError("call failed")
        return self.call_result


class FakeMCPManager:
    """模拟 MCPManager：记录 call_tool(server_name, tool_name, arguments) 调用。"""

    def __init__(self, call_result=None):
        self.call_result = call_result or {"success": True, "result": []}
        self.calls = []

    async def call_tool(self, server_name, tool_name, arguments=None):
        self.calls.append((server_name, tool_name, arguments))
        return self.call_result


class TestSearchProvider:
    def test_find_mcp_search_tool(self):
        reg = FakeRegistry([FakeTool("web_search", category="mcp"), FakeTool("calc", "general")])
        assert _find_mcp_search_tool(reg) == "web_search"

    def test_find_mcp_search_tool_none(self):
        assert _find_mcp_search_tool(None) is None
        assert _find_mcp_search_tool(FakeRegistry([])) is None
        assert _find_mcp_search_tool(FakeRegistry([FakeTool("web_search", "general")])) is None

    @pytest.mark.asyncio
    async def test_provider_calls_registry_call_tool_fallback(self):
        # 无 mcp_manager 时回退 registry.call_tool（旧路径兼容）
        reg = FakeRegistry([FakeTool("free-search-mcp:web_search", "mcp")])
        provider = _build_mcp_search_provider(reg)
        assert provider is not None
        out = await provider("测试热点")
        assert reg.calls == [("free-search-mcp:web_search", {"query": "测试热点"})]
        assert out == [{"title": "标题", "link": "http://x", "snippet": "摘要"}]

    @pytest.mark.asyncio
    async def test_provider_uses_mcp_manager_when_available(self):
        # 有 mcp_manager 且工具带 tags 时走 MCPManager.call_tool（真实执行路径）
        reg = FakeRegistry([FakeTool("web_search", "mcp")])
        mgr = FakeMCPManager(call_result={"success": True, "result": [{"title": "T", "link": "http://m", "snippet": "S"}]})
        # 工具带 tags 才能解析出 server 名
        reg.tools[0].tags = ["free-search-mcp"]
        provider = _build_mcp_search_provider(reg, mgr)
        assert provider is not None
        out = await provider("q")
        assert mgr.calls == [("free-search-mcp", "web_search", {"query": "q"})]
        assert out == [{"title": "T", "link": "http://m", "snippet": "S"}]

    @pytest.mark.asyncio
    async def test_provider_uses_mcp_manager_and_returns_none_on_failure(self):
        reg = FakeRegistry([FakeTool("web_search", "mcp")])
        reg.tools[0].tags = ["free-search-mcp"]
        mgr = FakeMCPManager(call_result={"success": False, "error": "boom"})
        provider = _build_mcp_search_provider(reg, mgr)
        assert provider is not None
        assert await provider("q") is None

    def test_provider_none_without_mcp_search_tool(self):
        assert _build_mcp_search_provider(FakeRegistry([])) is None
        assert _build_mcp_search_provider(FakeRegistry([FakeTool("calc", "general")])) is None
        assert _build_mcp_search_provider(None) is None

    @pytest.mark.asyncio
    async def test_provider_returns_none_when_call_raises(self):
        reg = FakeRegistry([FakeTool("web_search", "mcp")], raise_on_call=True)
        provider = _build_mcp_search_provider(reg)
        assert provider is not None
        assert await provider("q") is None

    @pytest.mark.asyncio
    async def test_provider_returns_none_when_call_unsuccessful(self):
        reg = FakeRegistry(
            [FakeTool("web_search", "mcp")], call_result={"success": False, "error": "boom"}
        )
        provider = _build_mcp_search_provider(reg)
        assert provider is not None
        assert await provider("q") is None

    @pytest.mark.asyncio
    async def test_provider_returns_none_when_result_unnormalizable(self):
        reg = FakeRegistry([FakeTool("web_search", "mcp")], call_result={"success": True, "result": "nope"})
        provider = _build_mcp_search_provider(reg)
        assert provider is not None
        assert await provider("q") is None

    def test_normalize_various_shapes(self):
        assert _normalize_search_results(
            {"results": [{"title": "a", "link": "u", "snippet": "s"}]}
        ) == [{"title": "a", "link": "u", "snippet": "s"}]
        assert _normalize_search_results(
            [{"title": "a", "url": "u", "description": "s"}]
        ) == [{"title": "a", "link": "u", "snippet": "s"}]
        assert _normalize_search_results({}) is None
        assert _normalize_search_results("nope") is None
        assert _normalize_search_results([]) is None


class TestHotspotDegradation:
    @pytest.mark.asyncio
    async def test_no_provider_returns_empty(self):
        monitor = HotspotMonitor(search_provider=None, fallback=None)
        assert await monitor.get_hotspots(["热点"]) == []

    @pytest.mark.asyncio
    async def test_provider_returns_none_degrades_to_empty(self):
        async def provider(query):
            return None

        monitor = HotspotMonitor(search_provider=provider, fallback=None)
        assert await monitor.get_hotspots(["热点"]) == []


# ================================================================ ⑤ 集成：setup_autonomy 注入
@pytest.mark.asyncio
async def test_setup_autonomy_injects_search_provider_from_services(tmp_path):
    import server.autonomy.main as autonomy_main
    from server.autonomy.config import AutonomyConfig, save_config
    from server.core.cxfc.manager import CXFCManager

    cxfc = CXFCManager(storage_path=str(tmp_path / "cxfc.db"))
    await cxfc._storage.init_db()

    class FakeServices:
        def __init__(self):
            self.cxfc_manager = cxfc
            self.autonomy_manager = None
            self.tool_registry = FakeRegistry([FakeTool("free-search-mcp:web_search", "mcp")])

    services = FakeServices()
    cfg = AutonomyConfig(store_path=str(tmp_path), enabled=True)
    save_config(cfg)

    manager = await setup_autonomy(services, store_path=str(tmp_path))
    assert manager is not None
    monitor = autonomy_main._search_monitor
    assert monitor is not None
    assert monitor.search_provider is not None

    # 经 handler 走 MCP 搜索 → 归一化结果
    out = await get_handlers()["autonomy_search"]("测试查询", limit=3)
    assert out == [{"title": "标题", "link": "http://x", "snippet": "摘要"}]

    if getattr(services, "autonomy_engine", None) is not None:
        await services.autonomy_engine.stop()
    await cxfc.shutdown()
