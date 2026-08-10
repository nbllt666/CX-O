"""server.core.plugins.manager (PluginManager) 单元测试。

覆盖插件发现/加载（依赖与冲突校验）、启用/禁用、钩子注册与执行、
配置更新、卸载、关闭、统计等核心逻辑。文件系统类用例用 tmp_path 隔离。

运行：python -m pytest tests/test_plugin_manager.py -v
"""
import json
from datetime import datetime

import pytest

from server.core.plugins.manager import PluginManager
from server.core.plugins.models import HookType, Plugin, PluginMetadata, PluginResult


def _plugin(id="p1", name="插件1", requires=None, conflicts=None):
    return PluginMetadata(
        id=id,
        name=name,
        requires=requires or [],
        conflicts=conflicts or [],
    )


def _register_enabled_plugin(mgr, plugin_id="p1", instance=None):
    """直接登记一个已启用插件（绕过文件系统加载）。"""
    plugin = Plugin(
        metadata=_plugin(id=plugin_id),
        enabled=True,
        instance=instance,
        loaded_at=datetime.now(),
    )
    mgr.plugins[plugin_id] = plugin
    return plugin


def _write_manifest(plugin_dir, metadata_dict):
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps(metadata_dict, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------- 发现
class TestDiscover:
    def test_discovers_plugins(self, tmp_path):
        _write_manifest(tmp_path / "p1", {"id": "p1", "name": "插件一"})
        _write_manifest(tmp_path / "p2", {"id": "p2", "name": "插件二"})
        mgr = PluginManager(str(tmp_path))
        found = mgr.discover_plugins()
        assert {m.id for m in found} == {"p1", "p2"}

    def test_skips_dir_without_manifest(self, tmp_path):
        _write_manifest(tmp_path / "p1", {"id": "p1", "name": "插件一"})
        (tmp_path / "nodir_manifest").write_text("x", encoding="utf-8")  # 文件非目录
        (tmp_path / "empty").mkdir()  # 目录但无 plugin.json
        mgr = PluginManager(str(tmp_path))
        found = mgr.discover_plugins()
        assert [m.id for m in found] == ["p1"]

    def test_skips_invalid_manifest(self, tmp_path):
        (tmp_path / "bad").mkdir()
        (tmp_path / "bad" / "plugin.json").write_text("not json", encoding="utf-8")
        mgr = PluginManager(str(tmp_path))
        assert mgr.discover_plugins() == []


# ---------------------------------------------------------------- 加载
class TestLoad:
    def test_load_missing_returns_none(self, tmp_path):
        mgr = PluginManager(str(tmp_path))
        assert mgr.load_plugin("ghost") is None

    def test_load_success_without_module(self, tmp_path):
        _write_manifest(tmp_path / "p1", {"id": "p1", "name": "插件一"})
        mgr = PluginManager(str(tmp_path))
        plugin = mgr.load_plugin("p1")
        assert plugin is not None
        assert plugin.metadata.id == "p1"
        assert plugin.module is None
        assert plugin.instance is None
        assert mgr.get_plugin("p1") is plugin

    def test_load_missing_dependency(self, tmp_path):
        _write_manifest(tmp_path / "p1", {"id": "p1", "name": "插件一", "requires": ["dep"]})
        mgr = PluginManager(str(tmp_path))
        assert mgr.load_plugin("p1") is None

    def test_load_conflict(self, tmp_path):
        _write_manifest(tmp_path / "a", {"id": "a", "name": "A"})
        _write_manifest(tmp_path / "b", {"id": "b", "name": "B", "conflicts": ["a"]})
        mgr = PluginManager(str(tmp_path))
        mgr.load_plugin("a")
        assert mgr.load_plugin("b") is None

    def test_load_already_loaded_returns_existing(self, tmp_path):
        _write_manifest(tmp_path / "p1", {"id": "p1", "name": "插件一"})
        mgr = PluginManager(str(tmp_path))
        first = mgr.load_plugin("p1")
        second = mgr.load_plugin("p1")
        assert first is second


# ---------------------------------------------------------------- 钩子
class TestHooks:
    def test_register_hook_sorts_by_priority(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")
        _register_enabled_plugin(mgr, "p2")
        mgr.register_hook("p1", HookType.CHAT_BEFORE, lambda e: None, priority=50)
        mgr.register_hook("p2", HookType.CHAT_BEFORE, lambda e: None, priority=10)
        hooks = mgr.hooks[HookType.CHAT_BEFORE]
        assert [h.priority for h in hooks] == [10, 50]

    @pytest.mark.asyncio
    async def test_execute_no_hooks(self):
        mgr = PluginManager()
        results = await mgr.execute_hooks(HookType.CHAT_BEFORE, {})
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_skips_disabled_plugin(self):
        mgr = PluginManager()
        plugin = _register_enabled_plugin(mgr, "p1")
        plugin.enabled = False
        mgr.register_hook("p1", HookType.CHAT_BEFORE, lambda e: PluginResult(success=True))
        results = await mgr.execute_hooks(HookType.CHAT_BEFORE, {})
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_sync_handler_returns_dict(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")
        mgr.register_hook(
            "p1", HookType.CHAT_BEFORE, lambda e: {"success": True, "data": {"x": 1}}
        )
        results = await mgr.execute_hooks(HookType.CHAT_BEFORE, {})
        assert results[0].success is True
        assert results[0].data == {"x": 1}

    @pytest.mark.asyncio
    async def test_execute_async_handler(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")

        async def handler(event):
            return PluginResult(success=True, data="async")

        mgr.register_hook("p1", HookType.CHAT_BEFORE, handler)
        results = await mgr.execute_hooks(HookType.CHAT_BEFORE, {})
        assert results[0].data == "async"

    @pytest.mark.asyncio
    async def test_execute_none_result_becomes_success(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")
        mgr.register_hook("p1", HookType.CHAT_BEFORE, lambda e: None)
        results = await mgr.execute_hooks(HookType.CHAT_BEFORE, {})
        assert results[0].success is True

    @pytest.mark.asyncio
    async def test_execute_handler_error(self):
        mgr = PluginManager()
        plugin = _register_enabled_plugin(mgr, "p1")

        def handler(event):
            raise RuntimeError("boom")

        mgr.register_hook("p1", HookType.CHAT_BEFORE, handler)
        results = await mgr.execute_hooks(HookType.CHAT_BEFORE, {})
        assert results[0].success is False
        assert results[0].error == "boom"
        assert plugin.errors == 1

    @pytest.mark.asyncio
    async def test_execute_stop_on_modify(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")
        calls = []

        def h1(event):
            calls.append("h1")
            return PluginResult(success=True, modified=True, stop_propagation=True)

        def h2(event):
            calls.append("h2")

        mgr.register_hook("p1", HookType.CHAT_BEFORE, h1)
        mgr.register_hook("p1", HookType.CHAT_BEFORE, h2)
        await mgr.execute_hooks(HookType.CHAT_BEFORE, {}, stop_on_modify=True)
        assert calls == ["h1"]

    @pytest.mark.asyncio
    async def test_execute_increments_hook_calls(self):
        mgr = PluginManager()
        plugin = _register_enabled_plugin(mgr, "p1")
        mgr.register_hook("p1", HookType.CHAT_BEFORE, lambda e: None)
        await mgr.execute_hooks(HookType.CHAT_BEFORE, {})
        assert plugin.hook_calls == 1


# ---------------------------------------------------------------- 启用/禁用
class TestEnableDisable:
    def test_enable_missing_plugin(self, tmp_path):
        mgr = PluginManager(str(tmp_path))
        assert mgr.enable_plugin("nope") is False

    def test_enable_with_sync_initialize(self, tmp_path):
        _write_manifest(tmp_path / "p1", {"id": "p1", "name": "插件一"})

        class DemoPlugin:
            def __init__(self):
                self.initialized = False

            def initialize(self, context):
                self.initialized = True

            def shutdown(self):
                pass

        mgr = PluginManager(str(tmp_path))
        plugin = mgr.load_plugin("p1")
        plugin.instance = DemoPlugin()
        assert mgr.enable_plugin("p1") is True
        assert plugin.enabled is True
        assert plugin.instance.initialized is True

    @pytest.mark.asyncio
    async def test_disable_runs_shutdown_and_clears_hooks(self):
        mgr = PluginManager()
        plugin = _register_enabled_plugin(mgr, "p1")
        mgr.register_hook("p1", HookType.CHAT_AFTER, lambda e: None)
        assert await mgr.disable_plugin("p1") is True
        assert plugin.enabled is False
        assert mgr.hooks == {HookType.CHAT_AFTER: []}

    @pytest.mark.asyncio
    async def test_disable_missing(self):
        mgr = PluginManager()
        assert await mgr.disable_plugin("nope") is False

    @pytest.mark.asyncio
    async def test_unload_plugin(self, tmp_path):
        _write_manifest(tmp_path / "p1", {"id": "p1", "name": "插件一"})
        mgr = PluginManager(str(tmp_path))
        mgr.load_plugin("p1")
        assert await mgr.unload_plugin("p1") is True
        assert mgr.get_plugin("p1") is None

    @pytest.mark.asyncio
    async def test_unload_missing(self, tmp_path):
        mgr = PluginManager(str(tmp_path))
        assert await mgr.unload_plugin("nope") is False


# ---------------------------------------------------------------- 配置
class TestConfig:
    def test_update_config_missing(self):
        mgr = PluginManager()
        assert mgr.update_plugin_config("nope", {}) is False

    def test_update_config_merges(self):
        mgr = PluginManager()
        plugin = _register_enabled_plugin(mgr)
        assert mgr.update_plugin_config("p1", {"a": 1}) is True
        assert plugin.config["a"] == 1


# ---------------------------------------------------------------- 统计
class TestStats:
    def test_stats(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")
        _register_enabled_plugin(mgr, "p2")
        plugin3 = _register_enabled_plugin(mgr, "p3")
        plugin3.enabled = False
        mgr.register_hook("p1", HookType.CHAT_BEFORE, lambda e: None)
        stats = mgr.get_stats()
        assert stats["total_plugins"] == 3
        assert stats["enabled_plugins"] == 2
        assert stats["total_hooks"] == 1
        assert len(stats["plugins"]) == 3

    def test_get_enabled_plugins(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")
        p2 = _register_enabled_plugin(mgr, "p2")
        p2.enabled = False
        ids = [p.metadata.id for p in mgr.get_enabled_plugins()]
        assert ids == ["p1"]


# ---------------------------------------------------------------- 关闭
class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_disables_enabled(self):
        mgr = PluginManager()
        _register_enabled_plugin(mgr, "p1")
        await mgr.shutdown()
        assert mgr.plugins["p1"].enabled is False