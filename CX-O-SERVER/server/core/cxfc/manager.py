"""CXFC 插件管理器——插件生命周期、事件分发与调用编排。"""
import asyncio
import base64
import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

import httpx

from server.core.logging_config import get_contextual_logger

from .models import CXFCPluginInfo, PluginStatus, SkillDefinition, CXFCEvent, CXFCRegisterRequest
from .storage import CXFCStorage
from .skill_registry import SkillRegistry

logger = get_contextual_logger(__name__)


class CXFCManager:
    """CXFC 插件管理器——负责插件注册、连接、心跳、工具/技能注册与事件分发。"""

    def __init__(
        self,
        storage_path: str = "data/cxfc_plugins.db",
        heartbeat_timeout: int = 30,
        heartbeat_check_interval: int = 10,
        # B-1 修复：可注入的 httpx.AsyncClient 工厂，便于单测模拟专用 TLS client 的构建参数。
        _client_factory: Optional[Callable[..., httpx.AsyncClient]] = None,
    ):
        self._storage = CXFCStorage(storage_path)
        self._skill_registry = SkillRegistry()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._tool_registry = None
        self._plugins: Dict[str, CXFCPluginInfo] = {}
        # BUG-B07 修复: 保护共享 _plugins dict 的并发读写
        self._plugins_lock = asyncio.Lock()
        self._heartbeat_timeout = heartbeat_timeout
        self._heartbeat_check_interval = heartbeat_check_interval
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._ws_manager = None
        self._on_event_callback: Optional[Callable] = None
        # B5 修复: 初始化 _background_tasks 集合，供 _track_background_task 使用
        self._background_tasks: set = set()
        # B-1 修复：带 TLS 证书插件的专用 HTTPS client 与其 CA 文件路径（按 plugin_id 索引）。
        self._client_factory: Callable[..., httpx.AsyncClient] = _client_factory or httpx.AsyncClient
        self._tls_clients: Dict[str, httpx.AsyncClient] = {}
        self._tls_ca_paths: Dict[str, str] = {}
        self._tls_dir: Optional[Path] = None

    def _track_background_task(self, task: asyncio.Task) -> asyncio.Task:
        """追踪后台任务，防止被GC回收；任务完成后自动从集合中移除"""
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    # ---------------------------------------------------------------------
    # B-1 修复：TLS 插件 scheme/client 选择与 CA 证书固定（TOFU 首次信任）
    # ---------------------------------------------------------------------
    @staticmethod
    def _normalize_fingerprint(fp: str) -> str:
        """将指纹统一为大写十六进制（去掉冒号分隔），兼容 Electron 冒号分隔形式。"""
        return "".join(fp.split(":")).upper()

    @staticmethod
    def _cert_fingerprint(pem: str) -> str:
        """由 PEM 原文计算证书 DER 的 SHA-256 指纹（大写十六进制，无冒号）。"""
        body = "".join(
            line.strip()
            for line in pem.splitlines()
            if not line.strip().startswith("-----")
        )
        der = base64.b64decode(body)
        return hashlib.sha256(der).hexdigest().upper()

    def _get_tls_dir(self) -> Path:
        """TLS 插件 CA 文件存放目录（与存储同目录下的 cxfc_ca/）。"""
        if self._tls_dir is None:
            base = Path(self._storage.db_path).parent / "cxfc_ca"
            base.mkdir(parents=True, exist_ok=True)
            self._tls_dir = base
        return self._tls_dir

    def _scheme_for(self, plugin: CXFCPluginInfo) -> str:
        """带证书插件走 https，无证书旧插件走 http。"""
        return "https" if plugin.tls_cert_pem else "http"

    def _client_for(self, plugin: CXFCPluginInfo) -> httpx.AsyncClient:
        """带证书插件返回其专用 HTTPS client，无证书插件复用共享 http client。"""
        if not plugin.tls_cert_pem:
            return self._http_client
        return self._ensure_tls_client(plugin)

    def _ensure_tls_client(self, plugin: CXFCPluginInfo) -> httpx.AsyncClient:
        """为该插件构建/复用专用 HTTPS client。

        将插件注册时上报的确切证书 PEM 写入独立 CA 文件，并以 verify=<该CA文件>
        构建 client——httpx 会以此 CA 信任该插件的自签名证书，实现 TOFU 首次信任
        与证书固定（后端只信任注册时保存的这份确切证书，其指纹即注册指纹）。
        """
        client = self._tls_clients.get(plugin.plugin_id)
        if client is not None:
            return client

        ca_path = self._get_tls_dir() / f"{plugin.plugin_id}.pem"
        ca_path.write_text(plugin.tls_cert_pem, encoding="utf-8")
        self._tls_ca_paths[plugin.plugin_id] = str(ca_path)
        client = self._client_factory(timeout=10.0, verify=str(ca_path))
        self._tls_clients[plugin.plugin_id] = client
        return client

    async def _release_tls_client(self, plugin_id: str):
        """释放插件专用 HTTPS client 并清理 CA 文件，避免连接/文件泄漏。"""
        client = self._tls_clients.pop(plugin_id, None)
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass
        ca = self._tls_ca_paths.pop(plugin_id, None)
        if ca:
            try:
                os.remove(ca)
            except OSError:
                pass

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
            # BUG-B07 修复: 在锁内写入 _plugins,避免与并发修改竞争
            async with self._plugins_lock:
                self._plugins[plugin.plugin_id] = plugin
            self._track_background_task(
                asyncio.create_task(self._connect_to_plugin_if_alive(plugin))
            )
        self._heartbeat_task = asyncio.create_task(self._check_heartbeats_loop())

    async def _connect_to_plugin_if_alive(self, plugin: CXFCPluginInfo):
        try:
            client = self._client_for(plugin)
            scheme = self._scheme_for(plugin)
            alive = await self._check_alive(plugin.host, plugin.port, client=client, scheme=scheme)
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

    async def _check_alive(self, host: str, port: int, client: httpx.AsyncClient = None, scheme: str = "http") -> bool:
        try:
            client = client or self._http_client
            resp = await client.get(f"{scheme}://{host}:{port}/health", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def _fetch_tools(self, host: str, port: int, client: httpx.AsyncClient = None, scheme: str = "http") -> List[Dict]:
        try:
            client = client or self._http_client
            resp = await client.get(f"{scheme}://{host}:{port}/tools", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("tools", [])
        except Exception:
            pass
        return []

    async def _fetch_skills(self, host: str, port: int, client: httpx.AsyncClient = None, scheme: str = "http") -> List[Dict]:
        try:
            client = client or self._http_client
            resp = await client.get(f"{scheme}://{host}:{port}/skills", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("skills", [])
        except Exception:
            pass
        return []

    async def _register_plugin_tools_and_skills(self, plugin: CXFCPluginInfo):
        client = self._client_for(plugin)
        scheme = self._scheme_for(plugin)
        tools = await self._fetch_tools(plugin.host, plugin.port, client=client, scheme=scheme)
        skills = await self._fetch_skills(plugin.host, plugin.port, client=client, scheme=scheme)
        plugin.tools = tools
        plugin.skills = skills

        self._register_catalog(plugin.plugin_id, tools, skills)
        await self._storage.save_plugin(plugin)

    def _register_catalog(self, plugin_id: str, tools: List[Dict], skills: List[Dict]):
        """将插件声明的 tools/skills 注册进工具与技能注册表（DRY 共享）。"""
        if self._tool_registry:
            for tool in tools:
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

        for skill_data in skills:
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
        # BUG-B07 修复: 在锁内完成 _plugins 写入
        async with self._plugins_lock:
            self._plugins[plugin_id] = plugin
        return plugin

    async def register_plugin(self, request: CXFCRegisterRequest) -> CXFCPluginInfo:
        # B-1 修复：TLS 首次信任校验——若同时上报证书 PEM 与指纹，二者必须匹配，
        # 否则拒绝注册（防止注册与后续访问信任不一致的证书）。
        if request.tls_cert_pem and request.tls_cert_fingerprint:
            computed = self._cert_fingerprint(request.tls_cert_pem)
            if computed != self._normalize_fingerprint(request.tls_cert_fingerprint):
                raise ValueError(
                    "TLS 证书指纹与注册证书不匹配，已拒绝注册（首次信任校验失败）"
                )

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
            # Task3 电脑控制接入：保存注册令牌与 TLS 证书指纹，供后续转发 /call 认证
            token=request.token,
            tls_cert_fingerprint=request.tls_cert_fingerprint,
            # B-1 修复：保存自签名证书 PEM，用于 TOFU 首次信任（证书固定）与 https 访问
            tls_cert_pem=request.tls_cert_pem,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        self._register_catalog(plugin_id, request.tools, request.skills)

        await self._storage.save_plugin(plugin)
        # BUG-B07 修复: 在锁内完成 _plugins 写入
        async with self._plugins_lock:
            self._plugins[plugin_id] = plugin
        return plugin

    def _clear_catalog(self, plugin_id: str, tools: List[Dict]):
        """清理某插件已注册的 tools/skills（DRY 共享，供断开与刷新复用）。"""
        if self._tool_registry:
            for tool in tools:
                try:
                    tool_name = tool.get("name", "")
                    if hasattr(self._tool_registry, "delete_tool"):
                        self._tool_registry.delete_tool(tool_name)
                except Exception:
                    pass
        self._skill_registry.unregister_skills(plugin_id)

    async def disconnect_plugin(self, plugin_id: str, remove_persistent: bool = True):
        # BUG-B07 修复: 在锁内获取并删除插件,避免与 connect_to_plugin / heartbeat 等并发
        async with self._plugins_lock:
            plugin = self._plugins.pop(plugin_id, None)
        if not plugin:
            return

        self._clear_catalog(plugin_id, plugin.tools)

        # B-1 修复：释放该插件专用 TLS client 与 CA 文件，避免连接/文件泄漏
        await self._release_tls_client(plugin_id)

        if remove_persistent:
            await self._storage.delete_plugin(plugin_id)
        else:
            await self._storage.update_status(plugin_id, PluginStatus.DISCONNECTED)

    async def call_tool(self, plugin_id: str, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        # BUG-B07 修复: 在锁内读取插件引用
        async with self._plugins_lock:
            plugin = self._plugins.get(plugin_id)
        if not plugin or plugin.status != PluginStatus.CONNECTED:
            return {"success": False, "error": f"插件 {plugin_id} 不可用"}

        headers = {}
        body = {"tool": tool_name, "arguments": arguments or {}}
        # Task3 电脑控制接入：带令牌插件在转发 /call 时携带
        # Authorization: Bearer <token> 并通过唯一 request_id 满足防重放。
        # 无令牌的既有插件照常转发，保持兼容（不添加认证头与 request_id）。
        if plugin.token:
            headers["Authorization"] = f"Bearer {plugin.token}"
            body["request_id"] = str(uuid.uuid4())

        try:
            # B-1 修复：按插件是否有证书选择 scheme 与专用 HTTPS client（证书固定）
            client = self._client_for(plugin)
            scheme = self._scheme_for(plugin)
            resp = await client.post(
                f"{scheme}://{plugin.host}:{plugin.port}/call",
                json=body,
                headers=headers,
                timeout=30.0,
            )
            return resp.json()
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def update_heartbeat(self, plugin_id: str, port: int) -> bool:
        # BUG-B07 修复: 在锁内完成 plugin 查找
        async with self._plugins_lock:
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
        # BUG-B07 修复: 在锁内读取插件引用
        async with self._plugins_lock:
            plugin = self._plugins.get(plugin_id)
        if not plugin or plugin.status != PluginStatus.CONNECTED:
            return None

        self._clear_catalog(plugin_id, plugin.tools)

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
        # BUG-B07 修复: 在锁内对 _plugins 拷贝快照,避免迭代时字典被改
        async with self._plugins_lock:
            plugins_snapshot = list(self._plugins.items())
        for plugin_id, plugin in plugins_snapshot:
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
        """返回全部已注册插件信息的列表。"""
        # BUG-B07 修复: 在锁内拷贝,避免迭代时字典被改
        # 注: 此方法为同步,在事件循环线程内运行,dict 复制是原子的
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

        # B-1 修复：关闭所有插件专用 HTTPS client 并清理 CA 文件，避免泄漏
        for plugin_id in list(self._tls_clients.keys()):
            await self._release_tls_client(plugin_id)

        if self._http_client:
            await self._http_client.aclose()

        await self._storage.close()
