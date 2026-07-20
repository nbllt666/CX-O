# CXHMS 主系统 HTTP 客户端封装
import httpx
from typing import Any, Dict, List, Optional


class MainSystemClient:
    """主系统 HTTP 客户端，封装 CXFC 与 ACP 相关 API 调用。"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
        # 同步客户端：Streamlit 主要是同步使用
        # trust_env=False + proxy=None：禁用 Windows IE 注册表代理检测
        # （httpx 默认 trust_env=True 会读取 IE 代理 ProxyServer=127.0.0.1:7897，
        # 对 localhost 请求返回 502；与 server/main.py 入口 monkey-patch 行为对齐）
        # 详见 .trae/documents/20260719_模块0_CXFC路由注入修复.md 第五章
        self.client = httpx.Client(
            base_url=self.base_url,
            timeout=10.0,
            trust_env=False,
            proxy=None,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """统一请求封装。

        连接失败、超时、非 200 状态码时返回 {"success": False, "error": ...}；
        成功时返回解析后的 JSON dict。
        """
        try:
            response = self.client.request(method, path, json=json, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ===== CXFC 相关 =====

    def cxfc_register(
        self,
        host: str,
        port: int,
        name: str,
        tools: List[Dict[str, Any]],
        capabilities: List[str],
        skills: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """注册 CXFC 插件。"""
        body = {
            "host": host,
            "port": port,
            "name": name,
            "tools": tools,
            "capabilities": capabilities,
            "skills": skills,
        }
        return self._request("POST", "/api/cxfc/register", json=body)

    def cxfc_heartbeat(self, plugin_id: str, port: int) -> Dict[str, Any]:
        """发送 CXFC 心跳。"""
        body = {"plugin_id": plugin_id, "port": port}
        return self._request("POST", "/api/cxfc/heartbeat", json=body)

    def cxfc_discover(self) -> Dict[str, Any]:
        """发现 CXFC 插件。"""
        return self._request("GET", "/api/cxfc/discover")

    def cxfc_list_plugins(self) -> Dict[str, Any]:
        """列出 CXFC 已注册插件。"""
        return self._request("GET", "/api/cxfc/plugins")

    def cxfc_list_skills(self) -> Dict[str, Any]:
        """列出 CXFC 已注册 Skills。"""
        return self._request("GET", "/api/cxfc/skills")

    def cxfc_connect(self, host: str, port: int) -> Dict[str, Any]:
        """主动连接 CXFC 插件。"""
        body = {"host": host, "port": port}
        return self._request("POST", "/api/cxfc/connect", json=body)

    def cxfc_delete_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """删除 CXFC 插件。"""
        return self._request("DELETE", f"/api/cxfc/plugins/{plugin_id}")

    def cxfc_refresh_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """刷新 CXFC 插件信息。"""
        return self._request("POST", f"/api/cxfc/plugins/{plugin_id}/refresh")

    def cxfc_call_tool(
        self, plugin_id: str, tool: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用指定 CXFC 插件的工具。"""
        body = {"tool": tool, "arguments": arguments}
        return self._request("POST", f"/api/cxfc/plugins/{plugin_id}/call", json=body)

    def cxfc_push_event(
        self, from_port: int, event_type: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """推送 CXFC 事件。"""
        body = {"from_port": from_port, "event_type": event_type, "data": data}
        return self._request("POST", "/api/cxfc/event/push", json=body)

    # ===== ACP 相关 =====

    def acp_discover(self, timeout: float = 5.0) -> Dict[str, Any]:
        """发现 ACP Agents。"""
        body = {"timeout": timeout}
        return self._request("POST", "/api/acp/discover", json=body)

    def acp_list_agents(self, online_only: bool = False) -> Dict[str, Any]:
        """列出 ACP Agents。"""
        params = {"online_only": online_only}
        return self._request("GET", "/api/acp/agents", params=params)

    def acp_connect(self, agent_id: str, host: str, port: int) -> Dict[str, Any]:
        """连接 ACP Agent。"""
        body = {"agent_id": agent_id, "host": host, "port": port}
        return self._request("POST", "/api/acp/connect", json=body)

    def acp_disconnect(self, connection_id: str) -> Dict[str, Any]:
        """断开 ACP 连接。"""
        return self._request("DELETE", f"/api/acp/connect/{connection_id}")

    def acp_list_connections(self, local_only: bool = True) -> Dict[str, Any]:
        """列出 ACP 连接。"""
        params = {"local_only": local_only}
        return self._request("GET", "/api/acp/connections", params=params)

    def acp_create_group(
        self, name: str, description: str = "", max_members: int = 50
    ) -> Dict[str, Any]:
        """创建 ACP 群组。"""
        body = {
            "name": name,
            "description": description,
            "max_members": max_members,
        }
        return self._request("POST", "/api/acp/groups", json=body)

    def acp_list_groups(self) -> Dict[str, Any]:
        """列出 ACP 群组。"""
        return self._request("GET", "/api/acp/groups")

    def acp_join_group(self, group_id: str) -> Dict[str, Any]:
        """加入 ACP 群组。"""
        return self._request("POST", f"/api/acp/groups/{group_id}/join")

    def acp_leave_group(self, group_id: str) -> Dict[str, Any]:
        """退出 ACP 群组。"""
        return self._request("POST", f"/api/acp/groups/{group_id}/leave")

    def acp_send_message(
        self,
        to_agent_id: str,
        content: Dict[str, Any],
        msg_type: str = "chat",
    ) -> Dict[str, Any]:
        """发送 ACP 单聊消息。"""
        body = {
            "to_agent_id": to_agent_id,
            "to_group_id": None,
            "content": content,
            "msg_type": msg_type,
        }
        return self._request("POST", "/api/acp/send", json=body)

    def acp_send_group_message(
        self, group_id: str, content: Dict[str, Any]
    ) -> Dict[str, Any]:
        """发送 ACP 群聊消息。"""
        body = {"group_id": group_id, "content": content}
        return self._request("POST", "/api/acp/send/group", json=body)

    def acp_get_messages(
        self,
        agent_id: Optional[str] = None,
        group_id: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """获取 ACP 消息。"""
        params: Dict[str, Any] = {"limit": limit}
        if agent_id is not None:
            params["agent_id"] = agent_id
        if group_id is not None:
            params["group_id"] = group_id
        return self._request("GET", "/api/acp/messages", params=params)

    def acp_get_stats(self) -> Dict[str, Any]:
        """获取 ACP 统计信息。"""
        return self._request("GET", "/api/acp/stats")

    # ===== MCP 相关 =====

    def list_mcp_servers(self) -> Dict[str, Any]:
        """列出已注册的 MCP 服务器。"""
        return self._request("GET", "/api/tools/mcp/servers")

    def add_mcp_server(
        self,
        name: str,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        endpoint_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """添加 MCP 服务器。

        支持 stdio（command/args/env）与 SSE/HTTP（endpoint_url）两种接入方式。
        """
        body: Dict[str, Any] = {"name": name}
        if command is not None:
            body["command"] = command
        if args is not None:
            body["args"] = args
        if env is not None:
            body["env"] = env
        if endpoint_url is not None:
            body["endpoint_url"] = endpoint_url
        return self._request("POST", "/api/tools/mcp/servers", json=body)

    def remove_mcp_server(self, name: str) -> Dict[str, Any]:
        """移除指定 MCP 服务器。"""
        return self._request("DELETE", f"/api/tools/mcp/servers/{name}")

    def start_mcp_server(self, name: str) -> Dict[str, Any]:
        """启动指定 MCP 服务器。"""
        body = {"name": name}
        return self._request("POST", "/api/tools/mcp/servers/start", json=body)

    def stop_mcp_server(self, name: str) -> Dict[str, Any]:
        """停止指定 MCP 服务器。"""
        body = {"name": name}
        return self._request("POST", "/api/tools/mcp/servers/stop", json=body)

    def check_mcp_health(self, name: str) -> Dict[str, Any]:
        """检查指定 MCP 服务器健康状态。"""
        return self._request("GET", f"/api/tools/mcp/servers/{name}/health")

    def get_mcp_tools(self, name: str) -> Dict[str, Any]:
        """获取指定 MCP 服务器暴露的工具列表。"""
        return self._request("GET", f"/api/tools/mcp/servers/{name}/tools")

    def call_mcp_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """调用指定 MCP 服务器上的工具。"""
        body = {
            "server_name": server_name,
            "tool": tool_name,
            "arguments": arguments,
        }
        return self._request("POST", "/api/tools/mcp/call", json=body)

    def sync_mcp_tools(self) -> Dict[str, Any]:
        """同步所有 MCP 服务器的工具列表到主系统。"""
        return self._request("POST", "/api/tools/mcp/sync")

    def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        self.client.close()
