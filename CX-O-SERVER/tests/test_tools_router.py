"""server.api.routers.tools 路由测试。

monkeypatch server.core.tools.registry.tool_registry 为假 registry + set_service_state
注入假 MCP manager，隔离真实工具注册表。覆盖：
- 工具 CRUD：list / get / register / patch / delete / test / call / stats / export / import / openai
- MCP：list / add / remove / start / stop / health / tools / call / sync
- 异常映射：ToolError→400、不存在→404、运行异常→500

运行：python -m pytest tests/test_tools_router.py -v
"""
from typing import Any, Dict, List, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.dependencies import ServiceState, set_service_state
from server.core.exceptions import ToolError
from server.api.routers import tools as tools_router_mod
from server.api.routers.admin import verify_admin_api_key
from server.core.tools import registry as registry_mod


# --------------------------------------------------------------------------- #
# 假对象
# --------------------------------------------------------------------------- #
class FakeTool:
    def __init__(self, name="calc", category="general", enabled=True):
        self.name = name
        self.description = "desc"
        self.parameters = {}
        self.enabled = enabled
        self.version = "1.0.0"
        self.category = category
        self.tags = []
        self.examples = []
        self.updated_at = "2026-08-09T00:00:00"

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "version": self.version,
            "category": self.category,
            "tags": self.tags,
            "examples": self.examples,
            "updated_at": self.updated_at,
        }


class FakeRegistry:
    def __init__(self):
        self.tools: Dict[str, FakeTool] = {
            "calc": FakeTool("calc", "general"),
            "mcp_tool": FakeTool("mcp_tool", "mcp"),
        }
        self.calls = []

    def list_tools_dict(self, enabled_only=True, include_builtin=False):
        result = {}
        for name, t in self.tools.items():
            if enabled_only and not t.enabled:
                continue
            result[name] = t.to_dict()
        return result

    def list_tools(self, enabled_only=False):
        return list(self.tools.values())

    def get_tool_stats(self):
        return {
            "total_tools": len(self.tools),
            "enabled_tools": sum(1 for t in self.tools.values() if t.enabled),
            "disabled_tools": sum(1 for t in self.tools.values() if not t.enabled),
            "total_calls": 0,
            "by_category": {},
            "top_tools": [],
        }

    def register(self, **kwargs):
        self.calls.append(("register", kwargs))
        name = kwargs["name"]
        self.tools[name] = FakeTool(name, kwargs["category"], kwargs["enabled"])

    def get_tool(self, name):
        return self.tools.get(name)

    def call_tool(self, name, arguments):
        self.calls.append(("call_tool", name, arguments))
        if name not in self.tools:
            return {"success": False, "error": "tool not found"}
        return {"success": True, "result": {"ok": True}}

    def list_openai_functions(self, enabled_only=True):
        return [{"name": n} for n in self.list_tools_dict(enabled_only)]

    def export_tools(self):
        return [t.to_dict() for t in self.tools.values()]

    def import_tools(self, tools):
        for t in tools:
            self.tools[t["name"]] = FakeTool(t["name"])
        return len(tools)

    def delete_tool(self, name):
        if name in self.tools:
            del self.tools[name]
            return True
        return False


class FakeMCPManager:
    def __init__(self):
        self.servers = {}
        self.calls = []

    async def list_servers(self):
        return []

    def get_stats(self):
        return {"total_servers": len(self.servers)}

    async def add_server(self, name, command, args, env):
        self.servers[name] = {"name": name}
        return {"name": name, "command": command}

    async def remove_server(self, name):
        if name in self.servers:
            del self.servers[name]
            return True
        return False

    async def start_server(self, name):
        return name in self.servers

    async def stop_server(self, name):
        return name in self.servers

    async def check_server_health(self, name):
        return name in self.servers

    async def get_tools(self, name):
        return [{"name": "t1"}]

    async def call_tool(self, server_name, tool_name, arguments):
        return {"ok": True}

    async def _sync_tools(self, server_name):
        pass


@pytest.fixture
def client(monkeypatch):
    fake_registry = FakeRegistry()
    monkeypatch.setattr(registry_mod, "tool_registry", fake_registry)
    import server.core.tools as core_tools_mod
    monkeypatch.setattr(core_tools_mod, "tool_registry", fake_registry)

    mcp = FakeMCPManager()
    state = ServiceState()
    state.mcp_manager = mcp
    set_service_state(state)

    app = FastAPI()
    app.include_router(tools_router_mod.router)
    # 写/执行端点已挂 verify_admin_api_key，测试中放行鉴权依赖
    app.dependency_overrides[verify_admin_api_key] = lambda: True
    return TestClient(app), fake_registry, mcp


# --------------------------------------------------------------------------- #
# 工具 CRUD
# --------------------------------------------------------------------------- #
class TestListTools:
    def test_success(self, client):
        c, reg, _ = client
        r = c.get("/tools")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert "calc" in body["tools"]
        assert body["statistics"]["total_tools"] == 2

    def test_category_filter(self, client):
        c, reg, _ = client
        r = c.get("/tools", params={"category": "mcp"})
        assert r.status_code == 200
        assert set(r.json()["tools"].keys()) == {"mcp_tool"}


class TestGetTool:
    def test_success(self, client):
        c, reg, _ = client
        r = c.get("/tools/calc")
        assert r.status_code == 200
        assert r.json()["tool"]["name"] == "calc"

    def test_not_found_404(self, client):
        c, reg, _ = client
        r = c.get("/tools/nope")
        assert r.status_code == 404


class TestRegisterTool:
    def test_success(self, client):
        c, reg, _ = client
        r = c.post("/tools", json={
            "name": "new_tool", "description": "d", "parameters": {},
        })
        assert r.status_code == 200
        assert "new_tool" in reg.tools

    def test_type_maps_to_category(self, client):
        c, reg, _ = client
        r = c.post("/tools", json={
            "name": "t2", "description": "d", "parameters": {},
            "type": "mcp", "category": "general",
        })
        assert r.status_code == 200
        assert reg.tools["t2"].category == "mcp"


class TestPatchTool:
    def test_success(self, client):
        c, reg, _ = client
        r = c.patch("/tools/calc", json={"enabled": False})
        assert r.status_code == 200
        assert reg.tools["calc"].enabled is False

    def test_status_maps_to_enabled(self, client):
        c, reg, _ = client
        r = c.patch("/tools/calc", json={"status": "inactive"})
        assert r.status_code == 200
        assert reg.tools["calc"].enabled is False

    def test_not_found_404(self, client):
        c, reg, _ = client
        r = c.patch("/tools/nope", json={"enabled": True})
        assert r.status_code == 404


class TestDeleteTool:
    def test_success(self, client):
        c, reg, _ = client
        r = c.delete("/tools/calc")
        assert r.status_code == 200
        assert "calc" not in reg.tools

    def test_not_found_404(self, client):
        c, reg, _ = client
        r = c.delete("/tools/nope")
        assert r.status_code == 404


class TestCallTool:
    def test_success(self, client):
        c, reg, _ = client
        r = c.post("/tools/call", json={"name": "calc", "arguments": {}})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_tool_error_400(self, client):
        c, reg, _ = client
        reg.call_tool = lambda name, args: {"success": False, "error": "boom"}
        r = c.post("/tools/call", json={"name": "calc", "arguments": {}})
        assert r.status_code == 400


class TestTestTool:
    def test_success(self, client):
        c, reg, _ = client
        r = c.post("/tools/calc/test", json={"arguments": {}})
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_not_found_404(self, client):
        c, reg, _ = client
        r = c.post("/tools/nope/test", json={"arguments": {}})
        assert r.status_code == 404


class TestStatsOpenaiExportImport:
    def test_stats(self, client):
        c, reg, _ = client
        r = c.get("/tools/stats")
        assert r.status_code == 200
        assert r.json()["statistics"]["total_tools"] == 2

    def test_openai_functions(self, client):
        c, reg, _ = client
        r = c.get("/tools/openai")
        assert r.status_code == 200
        assert len(r.json()["functions"]) == 2

    def test_export(self, client):
        c, reg, _ = client
        r = c.post("/tools/export")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_import(self, client):
        c, reg, _ = client
        r = c.post("/tools/import", json=[{"name": "imp1"}, {"name": "imp2"}])
        assert r.status_code == 200
        assert r.json()["count"] == 2


# --------------------------------------------------------------------------- #
# MCP 端点
# --------------------------------------------------------------------------- #
class TestMCP:
    def test_list_servers(self, client):
        c, reg, mcp = client
        r = c.get("/tools/mcp/servers")
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_add_server(self, client):
        c, reg, mcp = client
        r = c.post("/tools/mcp/servers", json={"name": "s1", "command": "cmd"})
        assert r.status_code == 200
        assert "s1" in mcp.servers

    def test_remove_server_success(self, client):
        c, reg, mcp = client
        mcp.servers["s1"] = {}
        r = c.delete("/tools/mcp/servers/s1")
        assert r.status_code == 200

    def test_remove_server_not_found_404(self, client):
        c, reg, mcp = client
        r = c.delete("/tools/mcp/servers/missing")
        assert r.status_code == 404

    def test_start_server(self, client):
        c, reg, mcp = client
        mcp.servers["s1"] = {}
        r = c.post("/tools/mcp/servers/start", json={"name": "s1"})
        assert r.status_code == 200

    def test_start_server_fail_400(self, client):
        c, reg, mcp = client
        r = c.post("/tools/mcp/servers/start", json={"name": "missing"})
        assert r.status_code == 400

    def test_stop_server(self, client):
        c, reg, mcp = client
        mcp.servers["s1"] = {}
        r = c.post("/tools/mcp/servers/stop", json={"name": "s1"})
        assert r.status_code == 200

    def test_health(self, client):
        c, reg, mcp = client
        mcp.servers["s1"] = {}
        r = c.get("/tools/mcp/servers/s1/health")
        assert r.status_code == 200
        assert r.json()["healthy"] is True

    def test_server_tools(self, client):
        c, reg, mcp = client
        r = c.get("/tools/mcp/servers/s1/tools")
        assert r.status_code == 200
        assert len(r.json()["tools"]) == 1

    def test_call_mcp_tool(self, client):
        c, reg, mcp = client
        r = c.post("/tools/mcp/call", json={
            "server_name": "s1", "tool_name": "t1", "arguments": {}})
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_sync(self, client):
        c, reg, mcp = client
        mcp.servers["s1"] = {}
        r = c.post("/tools/mcp/sync")
        assert r.status_code == 200
        assert r.json()["count"] == 1


# --------------------------------------------------------------------------- #
# 鉴权漏挂簇修复补充用例
# 说明：PATCH /tools/{name} 补挂 verify_admin_api_key 后新增鉴权用例；
# 既有用例经 client fixture 的 dependency_overrides 放行，不受影响。
# 项目统一口径：verify_admin_api_key 失败抛 403（对齐 test_stats_interrupt.py 既有断言）。
# --------------------------------------------------------------------------- #
@pytest.fixture
def raw_client(monkeypatch):
    """不挂鉴权 override 的客户端：用于真实校验 PATCH 端点的密钥门槛。"""
    fake_registry = FakeRegistry()
    monkeypatch.setattr(registry_mod, "tool_registry", fake_registry)
    import server.core.tools as core_tools_mod
    monkeypatch.setattr(core_tools_mod, "tool_registry", fake_registry)

    app = FastAPI()
    app.include_router(tools_router_mod.router)
    return TestClient(app), fake_registry


class TestPatchToolAuth:
    def test_patch_without_key_403(self, raw_client):
        # 无密钥（env 未配置）请求 → 403
        c, _ = raw_client
        r = c.patch("/tools/calc", json={"enabled": False})
        assert r.status_code == 403

    def test_patch_with_key_200(self, raw_client, monkeypatch):
        # 携带正确 X-API-Key → 200 且 patch 生效（对齐 setenv ADMIN_API_KEY 惰性注入模式）
        monkeypatch.setenv("ADMIN_API_KEY", "secret_key")
        c, reg = raw_client
        r = c.patch(
            "/tools/calc",
            json={"enabled": False},
            headers={"X-API-Key": "secret_key"},
        )
        assert r.status_code == 200
        assert reg.tools["calc"].enabled is False


class TestToolStatsError:
    def test_stats_error_branch_returns_error_status(self, client, monkeypatch):
        # /tools/stats 异常分支：不再谎报 success，返回 status=error + error 信息，计数保持 0
        c, reg, _ = client

        def _boom():
            raise RuntimeError("boom")

        monkeypatch.setattr(reg, "get_tool_stats", _boom)
        r = c.get("/tools/stats")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "error"
        assert "boom" in body["error"]
        # 计数结构保持全零，兼容前端消费方
        assert body["statistics"]["total_tools"] == 0
        assert body["statistics"]["by_category"] == {}