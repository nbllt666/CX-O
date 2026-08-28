"""MCP 工具管理——外部 MCP 服务器的连接、工具发现与调用。"""
import asyncio
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List

import httpx

from server.core.exceptions import MCPError
from server.core.logging_config import get_contextual_logger

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
            self.endpoint_url = "http://localhost:8600"

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


class MCPManager:
    """MCP管理器

    负责管理MCP服务器、工具同步和工具调用
    """

    def __init__(self):
        self.servers: Dict[str, MCPServer] = {}
        self._http_clients: Dict[str, httpx.AsyncClient] = {}
        self._tool_registry = None
        self._stdout_threads: Dict[str, threading.Thread] = {}
        self._stderr_threads: Dict[str, threading.Thread] = {}

    def set_tool_registry(self, tool_registry):
        """设置工具注册表

        Args:
            tool_registry: 工具注册表实例
        """
        self._tool_registry = tool_registry
        logger.info("MCP管理器已连接到工具注册表")

    def _unregister_server_tools(self, server_name: str) -> int:
        """注销指定 MCP 服务器注册进 ToolRegistry 的工具（幽灵工具清理）。

        MCP 工具以 category="mcp"、tags=[server_name] 注册；服务器移除/停止后，
        这些工具已不可调用，若不清理会成为"幽灵工具"——仍出现在工具列表中、
        被模型选中后在调用期才失败。逐个调用 registry.delete_tool 注销。

        Returns:
            实际注销的工具数量
        """
        registry = self._tool_registry
        if registry is None:
            return 0
        removed = 0
        for tool in list(registry.list_tools(enabled_only=False, include_builtin=True)):
            if tool.category == "mcp" and server_name in (tool.tags or []):
                if registry.delete_tool(tool.name):
                    removed += 1
        if removed:
            logger.info(f"已注销 MCP 服务器 {server_name} 的 {removed} 个注册工具")
        return removed

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
            endpoint_url=endpoint_url or "http://localhost:8600",
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
                    # 同步 wait 会阻塞事件循环最多 5 秒（与 stop_server/close 对齐），
                    # 卸载到 IO 线程执行
                    await asyncio.to_thread(server.process.wait, timeout=5)
                except subprocess.TimeoutExpired:
                    # L5: terminate 超时升级 kill + wait(3)，防止子进程残留
                    # （参照 service.py stop 的 terminate 超时 kill 升级模式）
                    logger.warning(f"MCP服务器进程 terminate 超时，升级 kill: {name}")
                    try:
                        server.process.kill()
                        await asyncio.to_thread(server.process.wait, timeout=3)
                    except Exception as kill_exc:
                        logger.warning(f"MCP服务器进程 kill 升级失败: {name}, {kill_exc}")
                except Exception as e:
                    logger.warning(f"停止MCP服务器进程失败: {e}")

            if name in self._http_clients:
                await self._http_clients[name].aclose()
                del self._http_clients[name]

            # 清理后台排空线程引用
            self._stdout_threads.pop(name, None)
            self._stderr_threads.pop(name, None)

            # 清理该 server 注册进 ToolRegistry 的幽灵工具
            self._unregister_server_tools(name)

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
            dangerous_chars = ["|", "&", ";", "$", "`", "(", ")", "<", ">", "\n", "\r"]
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
                # L5: communicate 加超时，防止流读取异常时无限阻塞事件循环
                stdout, stderr = process.communicate(timeout=5)
                error_msg = stderr.decode("utf-8") if stderr else "进程启动失败"
                server.status = "error"
                server.error = error_msg
                logger.error(f"MCP服务器启动失败: {name}, {error_msg}")
                raise MCPError(f"启动MCP服务器失败: {error_msg}")

            def _drain_stream(stream, log_func):
                try:
                    for line in stream:
                        log_func(line.decode().strip())
                except Exception as e:
                    logger.debug(f"MCP进程流排空异常: {e}")

            stdout_thread = threading.Thread(
                target=_drain_stream, args=(process.stdout, logger.debug), daemon=True
            )
            stdout_thread.name = f"mcp-stdout-drain-{name}"
            stdout_thread.start()
            stderr_thread = threading.Thread(
                target=_drain_stream, args=(process.stderr, logger.warning), daemon=True
            )
            stderr_thread.name = f"mcp-stderr-drain-{name}"
            stderr_thread.start()
            self._stdout_threads[name] = stdout_thread
            self._stderr_threads[name] = stderr_thread

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
                # BUG-B-M5 修复: process.wait() 是同步阻塞调用,在 async 函数中
                # 会阻塞事件循环最多 5 秒。改用 asyncio.to_thread 在独立线程执行。
                try:
                    await asyncio.to_thread(server.process.wait, timeout=5)
                except subprocess.TimeoutExpired:
                    # L5: 超时升级 kill + wait(3) 确保子进程终止，再按原语义抛错
                    # （参照 service.py stop 的 terminate 超时 kill 升级模式）
                    logger.warning(f"MCP服务器进程 terminate 超时，升级 kill: {name}")
                    server.process.kill()
                    await asyncio.to_thread(server.process.wait, timeout=3)
                    raise
                # 停止后该 server 的工具已不可调用，同步注销注册表中的幽灵工具
                self._unregister_server_tools(name)
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
            # trust_env=False + proxy=None 规避 Windows 系统代理对 localhost MCP 服务的
            # 502 干扰；仅 trust_env=False 时构造仍耗时 ~7s（对齐
            # core/utils.get_shared_http_client 实测结论，proxy=None 降至 ~10ms）
            if server_name not in self._http_clients:
                self._http_clients[server_name] = httpx.AsyncClient(
                    timeout=30.0, trust_env=False, proxy=None
                )

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
                        name = tool.get("name")
                        parameters = tool.get("parameters", {})
                        # 零校验修复：name 必须为非空 str、parameters 必须为 dict
                        # （对 parameters.type 做 object 宽松校验）；不合格跳过并告警，
                        # 避免畸形工具描述污染注册表后在调用期才暴露。
                        if not isinstance(name, str) or not name.strip():
                            logger.warning(
                                f"跳过非法 MCP 工具（name 非空字符串校验失败）: "
                                f"server={server_name}, name={name!r}"
                            )
                            continue
                        if not isinstance(parameters, dict):
                            logger.warning(
                                f"跳过非法 MCP 工具（parameters 非 dict）: "
                                f"server={server_name}, name={name}"
                            )
                            continue
                        if "type" in parameters and parameters.get("type") != "object":
                            logger.warning(
                                f"跳过非法 MCP 工具（parameters.type 应为 object）: "
                                f"server={server_name}, name={name}, type={parameters.get('type')!r}"
                            )
                            continue
                        try:
                            self._tool_registry.register(
                                name=name,
                                description=tool.get("description", ""),
                                parameters=parameters,
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
        except httpx.ConnectError:
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
            # trust_env=False + proxy=None 规避 Windows 系统代理对 localhost MCP 服务的
            # 502 干扰；仅 trust_env=False 时构造仍耗时 ~7s（对齐
            # core/utils.get_shared_http_client 实测结论，proxy=None 降至 ~10ms）
            if server_name not in self._http_clients:
                self._http_clients[server_name] = httpx.AsyncClient(
                    timeout=30.0, trust_env=False, proxy=None
                )

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
            error_msg = "MCP服务器响应超时"
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
                    # 同步 process.wait(timeout=5) 会阻塞事件循环最多 5 秒
                    # （与 stop_server 的 BUG-B-M5 修复对齐），卸载到 IO 线程执行
                    await asyncio.to_thread(server.process.wait, timeout=5)
                except subprocess.TimeoutExpired:
                    # L5: 超时升级 kill + wait(3)，防止管理器关闭时子进程残留
                    try:
                        server.process.kill()
                        await asyncio.to_thread(server.process.wait, timeout=3)
                    except Exception:
                        pass
                except Exception:
                    pass

        self.servers.clear()
        logger.info("MCP管理器已关闭")


async def start_configured_servers(
    mgr: "MCPManager", configs: List[Any], log=None
) -> None:
    """配置驱动的 MCP 服务器自注册/自启（P2-T1）。

    仅新增"配置驱动"入口，不改既有手动增删路径（add_server / remove_server /
    start_server / stop_server 保持原样）。对每个 enabled 的 server 依次执行
    add_server + start_server（start_server 内部已同步工具，此处再显式
    _sync_tools 一次兜底，幂等）；单个失败异常隔离并记录日志，不影响其余
    server；disabled 的 server 跳过，不注册不启动。

    Args:
        mgr: MCPManager 实例
        configs: 配置对象列表，每项须含 name/command/args/env/endpoint_url/enabled
                属性（与 MCPServerConfig 字段对齐，本函数不依赖具体配置模型）
        log: 日志记录器（缺省用模块 logger）

    Returns:
        None
    """
    log = log or logger
    for cfg in configs or []:
        name = getattr(cfg, "name", None) or getattr(cfg, "server_name", "") or ""
        if not getattr(cfg, "enabled", True):
            log.info("MCP 服务器 %s 配置为禁用，跳过自启", name)
            continue
        try:
            await mgr.add_server(
                name=name,
                command=getattr(cfg, "command", "") or "",
                args=list(getattr(cfg, "args", None) or []),
                env=dict(getattr(cfg, "env", None) or {}),
                endpoint_url=getattr(cfg, "endpoint_url", None),
            )
            await mgr.start_server(name)
            # start_server 内部已调用 _sync_tools；此处显式再同步一次兜底（幂等）
            await mgr._sync_tools(name)
        except Exception as e:
            log.error("配置驱动 MCP 服务器 %s 启动失败（已隔离，不影响其余）: %s", name, e)
