import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from backend.core.exceptions import MCPError
from backend.core.logging_config import get_contextual_logger

logger = get_contextual_logger(__name__)


@dataclass
class MCPServer:
    """MCP服务器信息

    Attributes:
        name: 服务器名称
        command: 启动命令（用于进程启动）
        args: 命令参数
        env: 环境变量
        endpoint_url: HTTP端点URL（用于API调用）
        status: 连接状态
        tools: 工具列表
        last_check: 最后检查时间
        error: 错误信息
        process: 进程对象
    """

    name: str
    command: str
    args: List[str]
    env: Dict[str, str]
    endpoint_url: str = ""
    status: str = "disconnected"
    tools: List[Dict] = None
    last_check: str = None
    error: str = None
    process: Any = None

    def __post_init__(self):
        """初始化后处理，自动设置endpoint_url"""
        if not self.endpoint_url:
            # 默认使用本地端口，格式: http://localhost:{port}
            # 这里使用一个默认端口，实际应该在添加服务器时指定
            self.endpoint_url = f"http://localhost:8001"

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "env": self.env,
            "endpoint_url": self.endpoint_url,
            "status": self.status,
            "tools": self.tools or [],
            "last_check": self.last_check,
            "error": self.error,
        }


class MCPConnectionError(Exception):
    """MCP连接错误"""

    pass


class MCPTimeoutError(Exception):
    """MCP超时错误"""

    pass


class MCPManager:
    """MCP管理器

    负责管理MCP服务器、工具同步和工具调用
    """

    def __init__(self):
        self.servers: Dict[str, MCPServer] = {}
        self._http_clients: Dict[str, httpx.AsyncClient] = {}
        self._tool_registry = None

    def set_tool_registry(self, tool_registry):
        """设置工具注册表

        Args:
            tool_registry: 工具注册表实例
        """
        self._tool_registry = tool_registry
        logger.info("MCP管理器已连接到工具注册表")

    async def add_server(
        self, name: str, command: str, args: List[str], env: Dict = None, endpoint_url: str = None
    ) -> Dict:
        """添加MCP服务器

        Args:
            name: 服务器名称
            command: 启动命令
            args: 命令参数
            env: 环境变量
            endpoint_url: HTTP端点URL（用于API调用）

        Returns:
            服务器信息字典
        """
        server = MCPServer(
            name=name,
            command=command,
            args=args,
            env=env or {},
            endpoint_url=endpoint_url or f"http://localhost:8001",
        )

        self.servers[name] = server
        logger.info(f"MCP服务器已添加: {name}, endpoint={server.endpoint_url}")

        return server.to_dict()

    async def remove_server(self, name: str) -> bool:
        """移除MCP服务器

        Args:
            name: 服务器名称

        Returns:
            是否成功移除
        """
        if name in self.servers:
            server = self.servers[name]

            if server.process:
                try:
                    server.process.terminate()
                    server.process.wait(timeout=5)
                except Exception as e:
                    logger.warning(f"停止MCP服务器进程失败: {e}")

            if name in self._http_clients:
                await self._http_clients[name].aclose()
                del self._http_clients[name]

            del self.servers[name]
            logger.info(f"MCP服务器已移除: {name}")
            return True
        return False

    async def start_server(self, name: str) -> bool:
        """启动MCP服务器

        Args:
            name: 服务器名称

        Returns:
            是否成功启动
        """
        server = self.servers.get(name)
        if not server:
            raise MCPError(f"服务器不存在: {name}")

        if server.status == "connected":
            logger.info(f"MCP服务器已在运行: {name}")
            return True

        try:
            env = os.environ.copy()
            env.update(server.env)

            # 验证命令和参数，防止命令注入
            if not server.command or not isinstance(server.command, str):
                raise MCPError(f"无效的命令: {server.command}")

            # 检查命令是否包含危险字符
            dangerous_chars = ["|", "&", ";", "$", "`", "(", ")", "<", ">"]
            if any(char in server.command for char in dangerous_chars):
                raise MCPError(f"命令包含危险字符: {server.command}")

            # 验证参数
            if server.args:
                if not isinstance(server.args, list):
                    raise MCPError(f"参数必须是列表: {type(server.args)}")
                for arg in server.args:
                    if not isinstance(arg, str):
                        raise MCPError(f"参数必须是字符串: {arg}")
                    if any(char in arg for char in dangerous_chars):
                        raise MCPError(f"参数包含危险字符: {arg}")

            # 启动进程
            process = subprocess.Popen(
                [server.command] + (server.args or []),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            server.process = process
            server.status = "connected"
            server.last_check = datetime.now().isoformat()
            server.error = None

            logger.info(
                f"MCP服务器已启动: {name}, PID: {process.pid}, endpoint={server.endpoint_url}"
            )

            # 等待服务器启动
            await asyncio.sleep(2)

            # 检查进程是否还在运行
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                error_msg = stderr.decode("utf-8") if stderr else "进程启动失败"
                server.status = "error"
                server.error = error_msg
                logger.error(f"MCP服务器启动失败: {name}, {error_msg}")
                raise MCPError(f"启动MCP服务器失败: {error_msg}")

            # 同步工具
            await self._sync_tools(name)

            return True
        except Exception as e:
            server.status = "error"
            server.error = str(e)
            logger.error(f"启动MCP服务器失败: {name}, {e}")
            raise MCPError(f"启动MCP服务器失败: {e}")

    async def stop_server(self, name: str) -> bool:
        """停止MCP服务器

        Args:
            name: 服务器名称

        Returns:
            是否成功停止
        """
        server = self.servers.get(name)
        if not server:
            raise MCPError(f"服务器不存在: {name}")

        if server.process:
            try:
                server.process.terminate()
                server.process.wait(timeout=5)
                server.status = "disconnected"
                server.last_check = datetime.now().isoformat()
                logger.info(f"MCP服务器已停止: {name}")
                return True
            except Exception as e:
                logger.error(f"停止MCP服务器失败: {name}, {e}")
                raise MCPError(f"停止MCP服务器失败: {e}")

        return False

    async def check_server_health(self, name: str) -> Dict:
        """检查MCP服务器健康状态

        Args:
            name: 服务器名称

        Returns:
            健康状态信息
        """
        server = self.servers.get(name)
        if not server:
            raise MCPError(f"服务器不存在: {name}")

        if server.process and server.process.poll() is None:
            server.status = "connected"
            server.last_check = datetime.now().isoformat()
            server.error = None
        else:
            server.status = "disconnected"
            server.last_check = datetime.now().isoformat()
            server.error = "进程已退出"

        return {
            "name": name,
            "status": server.status,
            "last_check": server.last_check,
            "error": server.error,
        }

    async def _sync_tools(self, server_name: str) -> None:
        """同步MCP服务器的工具

        Args:
            server_name: 服务器名称
        """
        server = self.servers.get(server_name)
        if not server:
            return

        try:
            if server_name not in self._http_clients:
                self._http_clients[server_name] = httpx.AsyncClient(timeout=30.0)

            client = self._http_clients[server_name]

            # 使用 endpoint_url 而非 command
            url = f"{server.endpoint_url}/tools"
            logger.debug(f"同步工具: {url}")

            response = await client.get(url, timeout=10.0)

            if response.status_code == 200:
                tools_data = response.json()
                server.tools = tools_data.get("tools", [])
                server.last_check = datetime.now().isoformat()

                if self._tool_registry:
                    for tool in server.tools:
                        try:
                            self._tool_registry.register(
                                name=tool.get("name"),
                                description=tool.get("description", ""),
                                parameters=tool.get("parameters", {}),
                                enabled=True,
                                version="1.0.0",
                                category="mcp",
                                tags=[server_name],
                            )
                        except Exception as e:
                            logger.warning(f"注册MCP工具失败: {tool.get('name')}, {e}")

                logger.info(f"MCP工具已同步: {server_name}, 工具数: {len(server.tools)}")
            else:
                error_detail = response.text[:200] if response.text else "无详细错误"
                logger.warning(f"获取MCP工具列表失败: {response.status_code}, {error_detail}")
                server.error = f"HTTP {response.status_code}: {error_detail}"
        except httpx.ConnectError as e:
            error_msg = f"无法连接到MCP服务器: {server.endpoint_url}"
            logger.error(f"同步MCP工具失败: {server_name}, {error_msg}")
            server.error = error_msg
        except Exception as e:
            logger.error(f"同步MCP工具失败: {server_name}, {e}")
            server.error = str(e)

    async def list_servers(self) -> List[Dict]:
        """列出所有MCP服务器

        Returns:
            服务器信息列表
        """
        return [s.to_dict() for s in self.servers.values()]

    async def get_tools(self, server_name: str) -> List[Dict]:
        """获取MCP服务器的工具

        Args:
            server_name: 服务器名称

        Returns:
            工具列表
        """
        server = self.servers.get(server_name)
        if not server:
            return []

        return server.tools or []

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict = None) -> Dict:
        """调用MCP工具

        Args:
            server_name: 服务器名称
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            调用结果
        """
        server = self.servers.get(server_name)
        if not server:
            return {"success": False, "error": f"服务器不存在: {server_name}"}

        if server.status != "connected":
            return {"success": False, "error": f"服务器未连接: {server_name}"}

        try:
            if server_name not in self._http_clients:
                self._http_clients[server_name] = httpx.AsyncClient(timeout=30.0)

            # 使用 endpoint_url 而非 command
            url = f"{server.endpoint_url}/call"
            logger.debug(f"调用工具: {url}, tool={tool_name}")

            response = await self._http_clients[server_name].post(
                url, json={"tool": tool_name, "arguments": arguments or {}}
            )

            if response.status_code == 200:
                return {"success": True, "result": response.json()}
            else:
                error_detail = response.text[:500] if response.text else "无详细错误"
                logger.error(f"MCP工具调用失败: {response.status_code}, {error_detail}")
                return {
                    "success": False,
                    "error": f"调用失败: HTTP {response.status_code}",
                    "detail": error_detail,
                }
        except httpx.ConnectError as e:
            error_msg = f"无法连接到MCP服务器: {server.endpoint_url}"
            logger.error(f"MCP工具调用失败: {e}")
            return {"success": False, "error": error_msg}
        except httpx.TimeoutException as e:
            error_msg = f"MCP服务器响应超时"
            logger.error(f"MCP工具调用超时: {e}")
            return {"success": False, "error": error_msg}
        except Exception as e:
            logger.error(f"MCP工具调用失败: {e}")
            return {"success": False, "error": str(e)}

    def get_stats(self) -> Dict:
        """获取MCP统计信息

        Returns:
            统计信息字典
        """
        return {
            "total_servers": len(self.servers),
            "connected_servers": sum(1 for s in self.servers.values() if s.status == "connected"),
            "disconnected_servers": sum(
                1 for s in self.servers.values() if s.status == "disconnected"
            ),
            "error_servers": sum(1 for s in self.servers.values() if s.status == "error"),
            "servers": [s.name for s in self.servers.values()],
        }

    async def close(self) -> None:
        """关闭MCP管理器"""
        for client in self._http_clients.values():
            await client.aclose()
        self._http_clients.clear()

        for server in self.servers.values():
            if server.process:
                try:
                    server.process.terminate()
                    server.process.wait(timeout=5)
                except Exception:
                    pass

        self.servers.clear()
        logger.info("MCP管理器已关闭")
