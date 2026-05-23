import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable

import httpx

from server.core.logging_config import get_contextual_logger

from .models import CXFCPluginInfo, PluginStatus, SkillDefinition, CXFCEvent, CXFCRegisterRequest
from .storage import CXFCStorage
from .skill_registry import SkillRegistry

logger = get_contextual_logger(__name__)


class CXFCManager:
    def __init__(
        self,
        storage_path: str = "data/cxfc_plugins.db",
        heartbeat_timeout: int = 30,
        heartbeat_check_interval: int = 10,
    ):
        self._storage = CXFCStorage(storage_path)
        self._skill_registry = SkillRegistry()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._tool_registry = None
        self._plugins: Dict[str, CXFCPluginInfo] = {}
        self._heartbeat_timeout = heartbeat_timeout
        self._heartbeat_check_interval = heartbeat_check_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ws_manager = None
        self._on_event_callback: Optional[Callable] = None

    def set_tool_registry(self, tool_registry):
        self._tool_registry = tool_registry

    def set_ws_manager(self, ws_manager):
        self._ws_manager = ws_manager

    def set_on_event_callback(self, callback: Callable):
        self._on_event_callback = callback

    async def start(self):
        await self._storage.init_db()
        plugins = await self._storage.load_plugins()
        self._http_client = httpx.AsyncClient(timeout=10.0)
        for plugin in plugins:
            self._plugins[plugin.plugin_id] = plugin
            asyncio.create_task(self._connect_to_plugin_if_alive(plugin))
        self._heartbeat_task = asyncio.create_task(self._check_heartbeats_loop())

    async def _connect_to_plugin_if_alive(self, plugin: CXFCPluginInfo):
        try:
            alive = await self._check_alive(plugin.host, plugin.port)
            if alive:
                await self._register_plugin_tools_and_skills(plugin)
                plugin.status = PluginStatus.CONNECTED
                await self._storage.update_status(plugin.plugin_id, PluginStatus.CONNECTED, datetime.now())
            else:
                plugin.status = PluginStatus.DISCONNECTED
                await self._storage.update_status(plugin.plugin_id, PluginStatus.DISCONNECTED)
        except Exception as e:
            logger.warning(f"连接插件 {plugin.plugin_id} 失败: {e}")
            plugin.status = PluginStatus.DISCONNECTED

    async def _check_alive(self, host: str, port: int) -> bool:
        try:
            resp = await self._http_client.get(f"http://{host}:{port}/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def _fetch_tools(self, host: str, port: int) -> List[Dict]:
        try:
            resp = await self._http_client.get(f"http://{host}:{port}/tools", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("tools", [])
        except Exception:
            pass
        return []

    async def _fetch_skills(self, host: str, port: int) -> List[Dict]:
        try:
            resp = await self._http_client.get(f"http://{host}:{port}/skills", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("skills", [])
        except Exception:
            pass
        return []

    async def _register_plugin_tools_and_skills(self, plugin: CXFCPluginInfo):
        tools = await self._fetch_tools(plugin.host, plugin.port)
        skills = await self._fetch_skills(plugin.host, plugin.port)
        plugin.tools = tools
        plugin.skills = skills

        if self._tool_registry:
            for tool in tools:
                try:
                    self._tool_registry.register(
                        name=tool.get("name", ""),
                        description=tool.get("description", ""),
                        parameters=tool.get("parameters", {}),
                        category="cxfc",
                        tags=[plugin.plugin_id],
                        enabled=True,
                    )
                except Exception as e:
                    logger.warning(f"注册工具 {tool.get('name')} 失败: {e}")

        for skill_data in skills:
            try:
                skill = SkillDefinition(
                    name=skill_data.get("name", ""),
                    description=skill_data.get("description", ""),
                    prompt_template=skill_data.get("prompt_template", ""),
                    trigger_keywords=skill_data.get("trigger_keywords", []),
                    trigger_events=skill_data.get("trigger_events", []),
                    auto_inject=skill_data.get("auto_inject", True),
                    source_plugin_id=plugin.plugin_id,
                )
                self._skill_registry.register_skill(skill)
            except Exception as e:
                logger.warning(f"注册 Skill {skill_data.get('name')} 失败: {e}")

        await self._storage.save_plugin(plugin)

    async def connect_to_plugin(self, host: str, port: int) -> Optional[CXFCPluginInfo]:
        alive = await self._check_alive(host, port)
        if not alive:
            return None

        try:
            resp = await self._http_client.get(f"http://{host}:{port}/health", timeout=5.0)
            health_data = resp.json()
            name = health_data.get("name", f"plugin_{port}")
            version = health_data.get("version", "1.0.0")
        except Exception:
            name = f"plugin_{port}"
            version = "1.0.0"

        plugin_id = f"cxfc_{host}_{port}"
        plugin = CXFCPluginInfo(
            plugin_id=plugin_id,
            host=host,
            port=port,
            name=name,
            version=version,
            status=PluginStatus.CONNECTED,
            last_seen=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        await self._register_plugin_tools_and_skills(plugin)
        self._plugins[plugin_id] = plugin
        return plugin

    async def register_plugin(self, request: CXFCRegisterRequest) -> CXFCPluginInfo:
        plugin_id = f"cxfc_{request.host}_{request.port}"
        plugin = CXFCPluginInfo(
            plugin_id=plugin_id,
            host=request.host,
            port=request.port,
            name=request.name,
            tools=request.tools,
            capabilities=request.capabilities,
            skills=request.skills,
            status=PluginStatus.CONNECTED,
            last_seen=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        if self._tool_registry:
            for tool in request.tools:
                try:
                    self._tool_registry.register(
                        name=tool.get("name", ""),
                        description=tool.get("description", ""),
                        parameters=tool.get("parameters", {}),
                        category="cxfc",
                        tags=[plugin_id],
                        enabled=True,
                    )
                except Exception as e:
                    logger.warning(f"注册工具 {tool.get('name')} 失败: {e}")

        for skill_data in request.skills:
            try:
                skill = SkillDefinition(
                    name=skill_data.get("name", ""),
                    description=skill_data.get("description", ""),
                    prompt_template=skill_data.get("prompt_template", ""),
                    trigger_keywords=skill_data.get("trigger_keywords", []),
                    trigger_events=skill_data.get("trigger_events", []),
                    auto_inject=skill_data.get("auto_inject", True),
                    source_plugin_id=plugin_id,
                )
                self._skill_registry.register_skill(skill)
            except Exception as e:
                logger.warning(f"注册 Skill {skill_data.get('name')} 失败: {e}")

        await self._storage.save_plugin(plugin)
        self._plugins[plugin_id] = plugin
        return plugin

    async def disconnect_plugin(self, plugin_id: str, remove_persistent: bool = True):
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return

        if self._tool_registry:
            for tool in plugin.tools:
                try:
                    tool_name = tool.get("name", "")
                    if hasattr(self._tool_registry, "delete_tool"):
                        self._tool_registry.delete_tool(tool_name)
                except Exception:
                    pass

        self._skill_registry.unregister_skills(plugin_id)

        del self._plugins[plugin_id]

        if remove_persistent:
            await self._storage.delete_plugin(plugin_id)
        else:
            await self._storage.update_status(plugin_id, PluginStatus.DISCONNECTED)

    async def call_tool(self, plugin_id: str, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        plugin = self._plugins.get(plugin_id)
        if not plugin or plugin.status != PluginStatus.CONNECTED:
            return {"success": False, "error": f"插件 {plugin_id} 不可用"}

        try:
            resp = await self._http_client.post(
                f"http://{plugin.host}:{plugin.port}/call",
                json={"tool": tool_name, "arguments": arguments or {}},
                timeout=30.0,
            )
            return resp.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def update_heartbeat(self, plugin_id: str, port: int) -> bool:
        if not plugin_id:
            for pid, p in self._plugins.items():
                if p.port == port:
                    plugin_id = pid
                    break

        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return False

        was_disconnected = plugin.status == PluginStatus.DISCONNECTED
        plugin.status = PluginStatus.CONNECTED
        plugin.last_seen = datetime.now()
        await self._storage.update_status(plugin_id, PluginStatus.CONNECTED, datetime.now())

        if was_disconnected:
            await self._register_plugin_tools_and_skills(plugin)

        return True

    async def push_event(self, event: CXFCEvent) -> bool:
        if self._ws_manager:
            try:
                await self._ws_manager.broadcast(
                    {
                        "type": "external_event",
                        "source": f"plugin_{event.from_port}",
                        "event_type": event.event_type,
                        "title": event.data.get("title", ""),
                        "body": event.data.get("content", event.data.get("body", "")),
                    }
                )
            except Exception as e:
                logger.warning(f"广播事件失败: {e}")

        matched_skills = self._skill_registry.find_by_event(event.event_type)
        if matched_skills and self._on_event_callback:
            for skill in matched_skills:
                try:
                    await self._on_event_callback(skill, event)
                except Exception as e:
                    logger.warning(f"触发 Skill {skill.name} 失败: {e}")

        return True

    async def refresh_plugin(self, plugin_id: str) -> Optional[CXFCPluginInfo]:
        plugin = self._plugins.get(plugin_id)
        if not plugin or plugin.status != PluginStatus.CONNECTED:
            return None

        if self._tool_registry:
            for tool in plugin.tools:
                tool_name = tool.get("name", "")
                if hasattr(self._tool_registry, "delete_tool"):
                    self._tool_registry.delete_tool(tool_name)
        self._skill_registry.unregister_skills(plugin_id)

        await self._register_plugin_tools_and_skills(plugin)
        return plugin

    async def _check_heartbeats_loop(self):
        while True:
            try:
                await asyncio.sleep(self._heartbeat_check_interval)
                await self._check_heartbeats()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"心跳检查异常: {e}")

    async def _check_heartbeats(self):
        now = datetime.now()
        for plugin_id, plugin in list(self._plugins.items()):
            if plugin.status != PluginStatus.CONNECTED:
                continue
            if plugin.last_seen and (now - plugin.last_seen).total_seconds() > self._heartbeat_timeout:
                logger.warning(f"插件 {plugin_id} 心跳超时")
                plugin.status = PluginStatus.DISCONNECTED
                await self._storage.update_status(plugin_id, PluginStatus.DISCONNECTED)

                if self._tool_registry:
                    for tool in plugin.tools:
                        tool_name = tool.get("name", "")
                        if hasattr(self._tool_registry, "delete_tool"):
                            self._tool_registry.delete_tool(tool_name)
                self._skill_registry.unregister_skills(plugin_id)

                if self._ws_manager:
                    try:
                        await self._ws_manager.broadcast(
                            {
                                "type": "plugin_status_changed",
                                "data": {
                                    "plugin_id": plugin_id,
                                    "status": "disconnected",
                                    "reason": "heartbeat_timeout",
                                },
                            }
                        )
                    except Exception:
                        pass

    def get_plugins(self) -> List[CXFCPluginInfo]:
        return list(self._plugins.values())

    def get_plugin(self, plugin_id: str) -> Optional[CXFCPluginInfo]:
        return self._plugins.get(plugin_id)

    def get_skill_registry(self) -> SkillRegistry:
        return self._skill_registry

    async def shutdown(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._http_client:
            await self._http_client.aclose()

        await self._storage.close()
