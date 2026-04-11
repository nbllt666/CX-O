import asyncio
import importlib
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from server.core.logging_config import get_contextual_logger

from .context import PluginContext
from .models import HookType, Plugin, PluginEvent, PluginHook, PluginMetadata, PluginResult

logger = get_contextual_logger(__name__)


class PluginManager:
    def __init__(self, plugins_dir: str = "plugins"):
        self.plugins_dir = Path(plugins_dir)
        self.plugins: Dict[str, Plugin] = {}
        self.hooks: Dict[HookType, List[PluginHook]] = {}
        self._context: Optional[PluginContext] = None
        self._plugin_tasks: Dict[str, Set[asyncio.Task]] = {}
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    def set_system_apis(self, memory_manager=None, context_manager=None, llm_client=None, tool_registry=None, ws_manager=None):
        self._system_apis = {"memory_manager": memory_manager, "context_manager": context_manager,
                            "llm_client": llm_client, "tool_registry": tool_registry, "ws_manager": ws_manager}

    def _create_context(self, plugin: Plugin) -> PluginContext:
        context = PluginContext(plugin_id=plugin.metadata.id, plugin_name=plugin.metadata.name,
                               config={**plugin.metadata.default_config, **plugin.config})
        if hasattr(self, "_system_apis"):
            context._memory_manager = self._system_apis.get("memory_manager")
            context._context_manager = self._system_apis.get("context_manager")
            context._llm_client = self._system_apis.get("llm_client")
            context._tool_registry = self._system_apis.get("tool_registry")
            context._ws_manager = self._system_apis.get("ws_manager")
        return context

    def _track_task(self, plugin_id: str, task: asyncio.Task):
        if plugin_id not in self._plugin_tasks:
            self._plugin_tasks[plugin_id] = set()
        self._plugin_tasks[plugin_id].add(task)
        task.add_done_callback(lambda t: self._untrack_task(plugin_id, t))

    def _untrack_task(self, plugin_id: str, task: asyncio.Task):
        if plugin_id in self._plugin_tasks:
            self._plugin_tasks[plugin_id].discard(task)

    async def _cancel_plugin_tasks(self, plugin_id: str):
        if plugin_id not in self._plugin_tasks:
            return
        tasks = list(self._plugin_tasks[plugin_id])
        for task in tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning(f"取消插件任务失败 {plugin_id}: {e}")
        self._plugin_tasks.pop(plugin_id, None)

    def _create_plugin_task(self, plugin_id: str, coro):
        task = asyncio.create_task(coro)
        self._track_task(plugin_id, task)
        return task

    def discover_plugins(self) -> List[PluginMetadata]:
        discovered = []
        for plugin_path in self.plugins_dir.iterdir():
            if not plugin_path.is_dir():
                continue
            manifest_path = plugin_path / "plugin.json"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                metadata = PluginMetadata(**manifest_data)
                discovered.append(metadata)
                logger.info(f"发现插件: {metadata.name} ({metadata.id})")
            except Exception as e:
                logger.error(f"加载插件清单失败 {plugin_path.name}: {e}")
        return discovered

    def load_plugin(self, plugin_id: str) -> Optional[Plugin]:
        if plugin_id in self.plugins:
            return self.plugins[plugin_id]
        plugin_path = self.plugins_dir / plugin_id
        manifest_path = plugin_path / "plugin.json"
        if not manifest_path.exists():
            logger.error(f"插件不存在: {plugin_id}")
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            metadata = PluginMetadata(**manifest_data)
            for dep in metadata.requires:
                if dep not in self.plugins:
                    logger.error(f"插件 {plugin_id} 缺少依赖: {dep}")
                    return None
            for conflict in metadata.conflicts:
                if conflict in self.plugins:
                    logger.error(f"插件 {plugin_id} 与 {conflict} 冲突")
                    return None
            module = None
            instance = None
            main_file = plugin_path / "__init__.py"
            if not main_file.exists():
                main_file = plugin_path / f"{plugin_id}.py"
            if main_file.exists():
                spec = importlib.util.spec_from_file_location(f"plugins.{plugin_id}", main_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[f"plugins.{plugin_id}"] = module
                    spec.loader.exec_module(module)
                    if hasattr(module, "Plugin"):
                        plugin_class = getattr(module, "Plugin")
                        instance = plugin_class()
            plugin = Plugin(metadata=metadata, loaded_at=datetime.now(), module=module, instance=instance)
            self.plugins[plugin_id] = plugin
            logger.info(f"插件已加载: {metadata.name}")
            return plugin
        except Exception as e:
            logger.error(f"加载插件失败 {plugin_id}: {e}")
            return None

    async def unload_plugin(self, plugin_id: str) -> bool:
        if plugin_id not in self.plugins:
            return False
        plugin = self.plugins[plugin_id]
        if plugin.enabled:
            await self.disable_plugin(plugin_id)
        for hook_type in list(self.hooks.keys()):
            self.hooks[hook_type] = [h for h in self.hooks[hook_type] if h.plugin_id != plugin_id]
        module_name = f"plugins.{plugin_id}"
        if module_name in sys.modules:
            del sys.modules[module_name]
        del self.plugins[plugin_id]
        logger.info(f"插件已卸载: {plugin_id}")
        return True

    def enable_plugin(self, plugin_id: str) -> bool:
        if plugin_id not in self.plugins:
            plugin = self.load_plugin(plugin_id)
            if not plugin:
                return False
        else:
            plugin = self.plugins[plugin_id]
        if plugin.enabled:
            return True
        try:
            context = self._create_context(plugin)
            if plugin.instance and hasattr(plugin.instance, "initialize"):
                if asyncio.iscoroutinefunction(plugin.instance.initialize):
                    self._create_plugin_task(plugin_id, plugin.instance.initialize(context))
                else:
                    plugin.instance.initialize(context)
            if plugin.instance and hasattr(plugin.instance, "get_hooks"):
                hooks = plugin.instance.get_hooks()
                for hook_type, handler in hooks.items():
                    self.register_hook(plugin_id, hook_type, handler)
            plugin.enabled = True
            logger.info(f"插件已启用: {plugin.metadata.name}")
            return True
        except Exception as e:
            logger.error(f"启用插件失败 {plugin_id}: {e}")
            return False

    async def disable_plugin(self, plugin_id: str) -> bool:
        if plugin_id not in self.plugins:
            return False
        plugin = self.plugins[plugin_id]
        if not plugin.enabled:
            return True
        try:
            await self._cancel_plugin_tasks(plugin_id)
            if plugin.instance and hasattr(plugin.instance, "shutdown"):
                if asyncio.iscoroutinefunction(plugin.instance.shutdown):
                    await plugin.instance.shutdown()
                else:
                    plugin.instance.shutdown()
            for hook_type in list(self.hooks.keys()):
                self.hooks[hook_type] = [h for h in self.hooks[hook_type] if h.plugin_id != plugin_id]
            plugin.enabled = False
            logger.info(f"插件已禁用: {plugin.metadata.name}")
            return True
        except Exception as e:
            logger.error(f"禁用插件失败 {plugin_id}: {e}")
            return False

    def register_hook(self, plugin_id: str, hook_type: HookType, handler: Callable, priority: int = 100):
        hook = PluginHook(type=hook_type, handler=handler, priority=priority, plugin_id=plugin_id)
        if hook_type not in self.hooks:
            self.hooks[hook_type] = []
        self.hooks[hook_type].append(hook)
        self.hooks[hook_type].sort(key=lambda h: h.priority)
        logger.debug(f"钩子已注册: {plugin_id} -> {hook_type.value}")

    async def execute_hooks(self, hook_type: HookType, event_data: Dict[str, Any], stop_on_modify: bool = False) -> List[PluginResult]:
        results = []
        if hook_type not in self.hooks:
            return results
        event = PluginEvent(type=hook_type, data=event_data)
        for hook in self.hooks[hook_type]:
            plugin = self.plugins.get(hook.plugin_id)
            if not plugin or not plugin.enabled:
                continue
            try:
                if asyncio.iscoroutinefunction(hook.handler):
                    result = await hook.handler(event)
                else:
                    result = hook.handler(event)
                if result is None:
                    result = PluginResult(success=True)
                elif isinstance(result, dict):
                    result = PluginResult(**result)
                elif not isinstance(result, PluginResult):
                    result = PluginResult(success=True, data=result)
                results.append(result)
                plugin.hook_calls += 1
                if stop_on_modify and result.modified and result.stop_propagation:
                    break
            except Exception as e:
                logger.error(f"钩子执行失败 {hook.plugin_id}/{hook_type.value}: {e}")
                plugin.errors += 1
                results.append(PluginResult(success=False, error=str(e)))
        return results

    def get_plugin(self, plugin_id: str) -> Optional[Plugin]:
        return self.plugins.get(plugin_id)

    def get_all_plugins(self) -> List[Plugin]:
        return list(self.plugins.values())

    def get_enabled_plugins(self) -> List[Plugin]:
        return [p for p in self.plugins.values() if p.enabled]

    def update_plugin_config(self, plugin_id: str, config: Dict[str, Any]) -> bool:
        if plugin_id not in self.plugins:
            return False
        plugin = self.plugins[plugin_id]
        plugin.config.update(config)
        if plugin.enabled and plugin.instance and hasattr(plugin.instance, "on_config_change"):
            try:
                if asyncio.iscoroutinefunction(plugin.instance.on_config_change):
                    self._create_plugin_task(plugin_id, plugin.instance.on_config_change(config))
                else:
                    plugin.instance.on_config_change(config)
            except Exception as e:
                logger.error(f"通知配置变更失败 {plugin_id}: {e}")
        return True

    async def shutdown(self):
        logger.info("正在关闭插件管理器...")
        for plugin_id in list(self.plugins.keys()):
            plugin = self.plugins[plugin_id]
            if plugin.enabled:
                try:
                    await self.disable_plugin(plugin_id)
                except Exception as e:
                    logger.error(f"禁用插件失败 {plugin_id}: {e}")
        for plugin_id in list(self._plugin_tasks.keys()):
            await self._cancel_plugin_tasks(plugin_id)
        logger.info("插件管理器已关闭")

    def get_stats(self) -> Dict[str, Any]:
        return {"total_plugins": len(self.plugins), "enabled_plugins": len(self.get_enabled_plugins()),
                "total_hooks": sum(len(hooks) for hooks in self.hooks.values()),
                "plugins": [{"id": p.metadata.id, "name": p.metadata.name, "enabled": p.enabled,
                           "hook_calls": p.hook_calls, "errors": p.errors,
                           "pending_tasks": len(self._plugin_tasks.get(p.metadata.id, set()))}
                          for p in self.plugins.values()]}


_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager(plugins_dir: str = "plugins") -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager(plugins_dir)
    return _plugin_manager