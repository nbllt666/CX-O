from fastapi import FastAPI
import uvicorn
import threading
import time
from tests.test_tools.common.api_client import MainSystemClient
from tests.test_tools.cxfc.preset_tools import execute_tool, list_tool_names, get_preset_skills


class MockPluginServer:
    """CXFC 模拟插件服务，用于测试主系统的插件注册、心跳与事件推送链路。

    支持预置工具的实际执行：当主系统通过 POST /call 调用预置工具时，
    会分发给 preset_tools.TOOL_HANDLERS 中对应的处理器执行。
    """

    def __init__(self, host: str = "localhost", port: int = 9000,
                 name: str = "测试插件", tools: list = None,
                 capabilities: list = None, skills: list = None,
                 main_system_url: str = "http://localhost:8000",
                 heartbeat_interval: float = 10.0):
        self.host = host
        self.port = port
        self.name = name
        self.tools = tools if tools is not None else []
        self.capabilities = capabilities if capabilities is not None else []
        # skills 默认加载预置 skills，便于测试主系统的 skills 链路
        self.skills = skills if skills is not None else get_preset_skills()
        self.main_system_url = main_system_url
        self.heartbeat_interval = heartbeat_interval

        # 状态存储
        self.events = []
        self.heartbeat_errors = []
        self.call_logs = []  # 工具调用日志
        self.plugin_id = None

        # 心跳线程控制
        self._heartbeat_thread = None
        self._heartbeat_stop_event = threading.Event()

        # FastAPI 应用与路由
        self.app = FastAPI()
        self._setup_routes()

        # uvicorn 服务器
        self._server = None
        self._server_thread = None

    def _setup_routes(self):
        @self.app.get("/health")
        async def health():
            return {"status": "ok"}

        @self.app.get("/tools")
        async def tools():
            return {"tools": self.tools}

        @self.app.get("/skills")
        async def skills():
            return {"skills": self.skills}

        @self.app.post("/event")
        async def event(event: dict):
            # 接收主系统推送的事件，原样存入列表
            self.events.append(event)
            return {"status": "ok"}

        @self.app.post("/call")
        async def call_tool(payload: dict):
            """工具调用端点：主系统通过此端点调用插件暴露的工具。

            请求格式：{"tool": "<tool_name>", "arguments": {...}}
            返回格式：{"success": true/false, "result": ..., "error": ...}
            """
            tool_name = payload.get("tool", "")
            arguments = payload.get("arguments", {}) or {}

            # 记录调用日志
            import datetime
            log_entry = {
                "tool": tool_name,
                "arguments": arguments,
                "called_at": datetime.datetime.now().isoformat(),
            }

            # 校验工具是否在已注册工具列表中
            registered_names = {t.get("name", "") for t in self.tools}
            if tool_name not in registered_names:
                log_entry["status"] = "rejected"
                log_entry["error"] = f"工具 {tool_name} 未注册"
                self.call_logs.append(log_entry)
                return {
                    "success": False,
                    "error": f"工具 {tool_name} 未在插件中注册",
                }

            # 优先使用预置工具处理器实际执行
            if tool_name in list_tool_names():
                result = execute_tool(tool_name, arguments)
                log_entry["status"] = "success" if result.get("success") else "failed"
                log_entry["result"] = result
                self.call_logs.append(log_entry)
                return result

            # 非预置工具（用户自定义）：返回 Mock 响应
            log_entry["status"] = "mocked"
            mock_result = {
                "success": True,
                "result": f"[mock] 工具 {tool_name} 被调用，参数: {arguments}",
                "tool": tool_name,
                "arguments": arguments,
            }
            log_entry["result"] = mock_result
            self.call_logs.append(log_entry)
            return mock_result

    def start(self):
        # 在后台 daemon 线程中启动 uvicorn 服务，非阻塞
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server_thread = threading.Thread(target=self._server.run, daemon=True)
        self._server_thread.start()

    def stop(self):
        # 先停心跳，再停 FastAPI 服务
        self.stop_heartbeat()
        if self._server is not None:
            self._server.should_exit = True
        if self._server_thread is not None:
            self._server_thread.join(timeout=5.0)

    def set_skills(self, skills: list) -> None:
        """动态更新插件暴露的 skills 列表。

        更新后 /skills 端点会返回新的 skills。注意：此方法不会自动同步到主系统，
        如需主系统感知变更，需要重新注册或刷新插件。
        """
        self.skills = list(skills) if skills is not None else []

    def register_to_main_system(self):
        # 调用主系统注册接口，获取并保存 plugin_id
        client = MainSystemClient(base_url=self.main_system_url)
        try:
            result = client.cxfc_register(
                host=self.host,
                port=self.port,
                name=self.name,
                tools=self.tools,
                capabilities=self.capabilities,
                skills=self.skills,
            )
            if result.get("success") is False:
                raise RuntimeError(f"注册失败: {result.get('error', '未知错误')}")
            self.plugin_id = result.get("plugin_id")
            return self.plugin_id
        finally:
            client.close()

    def start_heartbeat(self, plugin_id: str):
        # 启动后台 daemon 线程，周期性向主系统发送心跳
        self.plugin_id = plugin_id
        self._heartbeat_stop_event.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self):
        # 停止心跳线程
        self._heartbeat_stop_event.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=2.0)
            self._heartbeat_thread = None

    def _heartbeat_loop(self):
        # 心跳循环：每 heartbeat_interval 秒发送一次心跳，失败时记录错误并继续重试
        client = MainSystemClient(base_url=self.main_system_url)
        try:
            while not self._heartbeat_stop_event.wait(self.heartbeat_interval):
                try:
                    result = client.cxfc_heartbeat(plugin_id=self.plugin_id, port=self.port)
                    if result.get("success") is False:
                        self.heartbeat_errors.append(result.get("error", "未知错误"))
                except Exception as e:
                    self.heartbeat_errors.append(str(e))
        finally:
            client.close()
