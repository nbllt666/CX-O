"""dream/autonomy 彻底集成迁移测试（spec Task 6：去插件包装 + 配置迁入 UnifiedConfig + 生命周期补全）。

覆盖（对齐 .trae spec「enhance-cxfc-admin-and-integrate-dream」Task 6 验收）：
① 残留清理：历史 embedded 插件双形态条目（cxo-autonomy / embedded_cxo-autonomy）
   先造残留 → 经 manager 公开方法清理 → 断言双形态均移除（防恒真假闭合）；
   幂等（二次清理无变化）、manager 缺失静默、单条目异常隔离。
② 去插件包装集成：setup_autonomy 后 ToolRegistry 中 autonomy/dream 工具存在且
   category=="builtin"，GET /api/cxfc/plugins 口径（cxfc.get_plugins()）不含
   autonomy 插件条目，SkillRegistry 直注 source_plugin_id=="builtin"。
③ 配置迁移幂等：tmp 目录造旧 JSON → 迁移 → 值进 UnifiedConfig、旧文件成
   .migrated 留档 → 再跑一次无变化；非默认节不导入仅留档；非法旧档保留现场。
④ shutdown 清理断言：patch 引擎 stop 与 flush_physio_store，触发
   server.main._shutdown_dream_autonomy 断言全部被调、单项异常不影响其余。
⑤ 契约镜像与热更新登记：AutonomySection/DreamSection 与引擎侧 AutonomyConfig/
   DreamConfig 字段逐一同构（防双定义漂移）；REQUIRES_RESTART 登记两节。

运行：python -m pytest tests/test_autonomy_builtin_migration.py -q
"""
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.config import (
    AutonomySection,
    DreamSection,
    UnifiedConfig,
    migrate_legacy_autonomy_configs,
)
from server.config_hot_reload import REQUIRES_RESTART


# ================================================================ 公共夹具
@pytest.fixture
def isolated_settings(monkeypatch, tmp_path):
    """隔离 Settings 单例：CXO_CONFIG 指向 tmp 目录，防测试读写真实 config.json。

    yield (settings, config_path)；结束后 reset，让后续测试回归默认配置路径。
    """
    from server import config as config_module

    cfg_path = tmp_path / "config.json"
    monkeypatch.setenv("CXO_CONFIG", str(cfg_path))
    config_module.Settings.reset()
    yield config_module.get_settings(), cfg_path
    config_module.Settings.reset()


class FakeCxfcManager:
    """最小 cxfc manager 替身：仅暴露清理逻辑依赖的公开方法（get_plugin /
    disconnect_plugin），内存态记录移除调用与插件条目（不触碰 manager 内部实现）。"""

    def __init__(self):
        # plugin_id -> 伪插件对象（SimpleNamespace 足够，disconnect 仅透传 id）
        self._plugins = {}
        self.disconnected = []  # (plugin_id, remove_persistent)

    def get_plugin(self, plugin_id):
        return self._plugins.get(plugin_id)

    def get_plugins(self):
        return list(self._plugins.values())

    async def disconnect_plugin(self, plugin_id, remove_persistent=True):
        self.disconnected.append((plugin_id, remove_persistent))
        self._plugins.pop(plugin_id, None)


class _FakeAutonomyEngine:
    """仿 AutonomyEngine：stop 为 async，记录调用次数，可注入失败。"""

    def __init__(self, fail=False):
        self.fail = fail
        self.stop_calls = 0

    async def stop(self):
        self.stop_calls += 1
        if self.fail:
            raise RuntimeError("autonomy stop boom")


class _FakeDreamEngine:
    """仿 DreamEngine：stop 为 sync，记录调用次数，可注入失败。"""

    def __init__(self, fail=False):
        self.fail = fail
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        if self.fail:
            raise RuntimeError("dream stop boom")


# ================================================================ ① 残留清理（双形态）
@pytest.mark.asyncio
class TestLegacyPluginCleanup:
    async def test_both_forms_removed_after_seeding(self):
        """防恒真假闭合：先造双形态残留 → 清理 → 断言均移除、其余插件幸存。"""
        from server.autonomy.main import _cleanup_legacy_autonomy_plugins

        cxfc = FakeCxfcManager()
        cxfc._plugins["cxo-autonomy"] = SimpleNamespace(plugin_id="cxo-autonomy")
        cxfc._plugins["embedded_cxo-autonomy"] = SimpleNamespace(
            plugin_id="embedded_cxo-autonomy"
        )
        cxfc._plugins["cxfc_other_host_1"] = SimpleNamespace(plugin_id="cxfc_other_host_1")

        await _cleanup_legacy_autonomy_plugins(cxfc)

        ids = {p.plugin_id for p in cxfc.get_plugins()}
        assert "cxo-autonomy" not in ids
        assert "embedded_cxo-autonomy" not in ids
        assert "cxfc_other_host_1" in ids  # 无关插件不受牵连
        assert sorted(pid for pid, _ in cxfc.disconnected) == [
            "cxo-autonomy",
            "embedded_cxo-autonomy",
        ]
        # 持久化残留一并删除（remove_persistent=True）
        assert all(remove is True for _, remove in cxfc.disconnected)

    async def test_cleanup_idempotent(self):
        """二次清理幂等：条目已移除，再次执行无调用、无异常。"""
        from server.autonomy.main import _cleanup_legacy_autonomy_plugins

        cxfc = FakeCxfcManager()
        cxfc._plugins["embedded_cxo-autonomy"] = SimpleNamespace(
            plugin_id="embedded_cxo-autonomy"
        )
        await _cleanup_legacy_autonomy_plugins(cxfc)
        assert len(cxfc.disconnected) == 1
        await _cleanup_legacy_autonomy_plugins(cxfc)
        assert len(cxfc.disconnected) == 1  # 第二次 no-op

    async def test_cleanup_silently_skips_missing_manager(self):
        """manager 未启用（None）时静默跳过，不抛错。"""
        from server.autonomy.main import _cleanup_legacy_autonomy_plugins

        await _cleanup_legacy_autonomy_plugins(None)

    async def test_single_failure_isolated(self, caplog):
        """单个条目清理抛异常被隔离，其余条目仍被处理。"""
        from server.autonomy.main import _cleanup_legacy_autonomy_plugins

        class _HalfBrokenManager(FakeCxfcManager):
            async def disconnect_plugin(self, plugin_id, remove_persistent=True):
                if plugin_id == "cxo-autonomy":
                    raise RuntimeError("disconnect boom")
                await super().disconnect_plugin(plugin_id, remove_persistent)

        cxfc = _HalfBrokenManager()
        cxfc._plugins["cxo-autonomy"] = SimpleNamespace(plugin_id="cxo-autonomy")
        cxfc._plugins["embedded_cxo-autonomy"] = SimpleNamespace(
            plugin_id="embedded_cxo-autonomy"
        )
        with caplog.at_level(logging.WARNING):
            await _cleanup_legacy_autonomy_plugins(cxfc)
        # cxo-autonomy 失败被隔离；embedded_cxo-autonomy 仍被清理
        assert ("embedded_cxo-autonomy", True) in cxfc.disconnected
        assert "embedded_cxo-autonomy" not in {p.plugin_id for p in cxfc.get_plugins()}

    async def test_real_manager_db_residual_cleanup(self, tmp_path):
        """真实 CXFCManager + 临时 sqlite：注入 db 残留 → 清理后插件列表不含双形态。"""
        from server.core.cxfc.manager import CXFCManager
        from server.core.cxfc.models import CXFCPluginInfo, PluginStatus, PluginTransport
        from server.autonomy.main import _cleanup_legacy_autonomy_plugins

        cxfc = CXFCManager(storage_path=str(tmp_path / "cxfc.db"))
        await cxfc._storage.init_db()
        try:
            # 造历史残留：运行时形态 embedded_cxo-autonomy（模拟旧版
            # register_embedded_plugin 落库条目，GET /api/cxfc/plugins 口径可见）
            ghost = CXFCPluginInfo(
                plugin_id="embedded_cxo-autonomy",
                host="",
                port=0,
                name="CX-O-Autonomy",
                tools=[{"name": "autonomy_get_status"}],
                capabilities=["autonomy"],
                skills=[],
                status=PluginStatus.DISCONNECTED,
                transport=PluginTransport.EMBEDDED,
            )
            await cxfc._storage.save_plugin(ghost)
            async with cxfc._plugins_lock:
                cxfc._plugins[ghost.plugin_id] = ghost
            assert cxfc.get_plugin("embedded_cxo-autonomy") is not None

            await _cleanup_legacy_autonomy_plugins(cxfc)

            # 插件列表口径（get_plugins）与持久化口径（load_plugins）均无残留
            assert "embedded_cxo-autonomy" not in {p.plugin_id for p in cxfc.get_plugins()}
            remaining = await cxfc._storage.load_plugins()
            assert "embedded_cxo-autonomy" not in {p.plugin_id for p in remaining}
        finally:
            await cxfc.shutdown()


# ================================================================ ② 去插件包装：builtin 直注
@pytest.mark.asyncio
class TestBuiltinRegistration:
    async def test_setup_registers_builtin_tools_without_plugin_entry(self, tmp_path):
        """setup_autonomy 后：9 个 autonomy 工具 category=="builtin"、插件列表无条目。"""
        from server.autonomy.config import AutonomyConfig, save_config as _legacy_save
        from server.autonomy.main import TOOL_SPECS, get_handlers, setup_autonomy
        from server.core.cxfc.manager import CXFCManager
        from server.core.tools.registry import ToolRegistry

        # 旧档注入（迁移前兼容语义）：enabled=true
        _legacy_save(AutonomyConfig(store_path=str(tmp_path), enabled=True))

        tr = ToolRegistry()
        cxfc = CXFCManager(storage_path=str(tmp_path / "cxfc.db"))
        await cxfc._storage.init_db()
        cxfc.set_tool_registry(tr)

        class FakeServices:
            def __init__(self):
                self.cxfc_manager = cxfc
                self.tool_registry = tr
                self.autonomy_manager = None

        services = FakeServices()
        try:
            manager = await setup_autonomy(services, store_path=str(tmp_path))
            assert manager is not None

            # 插件列表口径不含 autonomy 条目（双形态覆盖）
            ids = {p.plugin_id for p in cxfc.get_plugins()}
            assert "cxo-autonomy" not in ids
            assert "embedded_cxo-autonomy" not in ids

            # 工具直注：全部 category=="builtin" 且 handler 已接线
            for spec in TOOL_SPECS:
                tool = tr.get_tool(spec["name"])
                assert tool is not None, f"工具 {spec['name']} 未注册"
                assert tool.category == "builtin"
                assert tool.enabled is True
                assert tool.function is get_handlers()[spec["name"]]

            # LLM 分发口径可正常调用（经 ToolRegistry 分发 → 状态契约形状）
            out = tr.call_tool("autonomy_get_status", {})
            assert out["success"] is True
            assert out["result"]["status"] == "running"

            # 技能直注：SkillRegistry 中 autonomy_loop 来源登记为 builtin
            skills = {s.name: s for s in cxfc.get_skill_registry().get_all_skills()}
            assert "autonomy_loop" in skills
            assert skills["autonomy_loop"].source_plugin_id == "builtin"

            # dream 未启用：dream 工具不注册（enabled 开关语义不变）
            assert tr.get_tool("dream_get_status") is None
        finally:
            if getattr(services, "autonomy_engine", None) is not None:
                await services.autonomy_engine.stop()
            await cxfc.shutdown()

    async def test_setup_without_cxfc_manager_still_registers_tools(self, tmp_path):
        """去插件包装后 cxfc manager 缺失仅降级：工具仍直注、装配不失败。"""
        from server.autonomy.config import AutonomyConfig, save_config as _legacy_save
        from server.autonomy.main import TOOL_SPECS, setup_autonomy
        from server.core.tools.registry import ToolRegistry

        _legacy_save(AutonomyConfig(store_path=str(tmp_path), enabled=True))
        tr = ToolRegistry()

        class FakeServices:
            def __init__(self):
                self.tool_registry = tr
                self.autonomy_manager = None

        services = FakeServices()
        try:
            manager = await setup_autonomy(services, store_path=str(tmp_path))
            assert manager is not None
            for spec in TOOL_SPECS:
                tool = tr.get_tool(spec["name"])
                assert tool is not None and tool.category == "builtin"
        finally:
            if getattr(services, "autonomy_engine", None) is not None:
                await services.autonomy_engine.stop()

    async def test_setup_registers_dream_tools_when_dream_enabled(self, tmp_path):
        """dream.enabled=true 时 dream 工具并入 builtin 直注（开关语义不变）。"""
        from server.autonomy.config import AutonomyConfig, save_config as _legacy_save
        from server.autonomy.dream.config import DreamConfig
        from server.autonomy.main import DREAM_TOOL_SPECS, setup_autonomy
        from server.core.cxfc.manager import CXFCManager
        from server.core.tools.registry import ToolRegistry

        _legacy_save(AutonomyConfig(store_path=str(tmp_path), enabled=True))
        # 旧档 dream_config.json（enabled=true）→ _load_effective_dream_config 走旧档
        from server.autonomy._atomic_io import atomic_write_json

        atomic_write_json(
            str(tmp_path / "dream_config.json"),
            DreamConfig(enabled=True).model_dump(),
        )

        tr = ToolRegistry()
        cxfc = CXFCManager(storage_path=str(tmp_path / "cxfc.db"))
        await cxfc._storage.init_db()
        cxfc.set_tool_registry(tr)

        class FakeServices:
            def __init__(self):
                self.cxfc_manager = cxfc
                self.tool_registry = tr
                self.autonomy_manager = None

        services = FakeServices()
        try:
            manager = await setup_autonomy(services, store_path=str(tmp_path))
            assert manager is not None
            for spec in DREAM_TOOL_SPECS:
                tool = tr.get_tool(spec["name"])
                assert tool is not None, f"工具 {spec['name']} 未注册"
                assert tool.category == "builtin"
            # dream 引擎已装配：dream_get_status 返回引擎状态（enabled=True → 非 disabled）
            out = tr.call_tool("dream_get_status", {})
            assert out["success"] is True
            assert out["result"]["enabled"] is True
            assert out["result"]["status"] in ("idle", "sleeping", "dreaming")
        finally:
            if getattr(services, "autonomy_engine", None) is not None:
                await services.autonomy_engine.stop()
            dream_engine = getattr(services, "dream_engine", None)
            if dream_engine is not None:
                dream_engine.stop()
            await cxfc.shutdown()


# ================================================================ ③ 配置迁移幂等
class TestConfigMigration:
    def test_migrate_imports_values_and_archives(self, isolated_settings, tmp_path):
        """旧 JSON 存在且节为默认 → 值导入 UnifiedConfig + 落盘 + 旧档 .migrated 留档。"""
        settings, cfg_path = isolated_settings
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "autonomy_config.json").write_text(
            json.dumps(
                {"enabled": True, "agent_id": "测试人设", "loop_interval_minutes": 30},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (legacy_dir / "dream_config.json").write_text(
            json.dumps({"enabled": True, "dream_temperature": 0.7}, ensure_ascii=False),
            encoding="utf-8",
        )

        results = migrate_legacy_autonomy_configs(legacy_dir=str(legacy_dir))

        assert results == {"autonomy": True, "dream": True}
        # 值进 UnifiedConfig（内存态）
        assert settings.config.autonomy.enabled is True
        assert settings.config.autonomy.agent_id == "测试人设"
        assert settings.config.autonomy.loop_interval_minutes == 30
        assert settings.config.dream.enabled is True
        assert settings.config.dream.dream_temperature == 0.7
        # 缺失字段由 Pydantic 默认补齐（auto_fill 语义）
        assert settings.config.autonomy.budget.daily_token_limit == 2000000
        assert settings.config.dream.physio.store_raw_hr is False
        # 旧文件改名留档（不删除）
        assert not (legacy_dir / "autonomy_config.json").exists()
        assert (legacy_dir / "autonomy_config.json.migrated").exists()
        assert not (legacy_dir / "dream_config.json").exists()
        assert (legacy_dir / "dream_config.json.migrated").exists()
        # 已持久化到 config.json（磁盘态）
        assert cfg_path.exists()
        persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert persisted["autonomy"]["agent_id"] == "测试人设"
        assert persisted["dream"]["dream_temperature"] == 0.7

    def test_migrate_idempotent_second_run_noop(self, isolated_settings, tmp_path):
        """幂等：迁移后二次启动（重置 settings 重读盘）不再触发导入。"""
        _, cfg_path = isolated_settings
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "autonomy_config.json").write_text(
            json.dumps({"enabled": True, "agent_id": "二次启动"}), encoding="utf-8"
        )
        first = migrate_legacy_autonomy_configs(legacy_dir=str(legacy_dir))
        assert first == {"autonomy": True, "dream": False}
        # 模拟二次启动：settings 重读盘（磁盘态已含迁移结果）
        from server import config as config_module

        config_module.Settings.reset()
        settings2 = config_module.get_settings()
        second = migrate_legacy_autonomy_configs(legacy_dir=str(legacy_dir))
        assert second == {"autonomy": False, "dream": False}
        assert settings2.config.autonomy.agent_id == "二次启动"  # 值保持不变

    def test_migrate_skips_import_when_section_customized(self, isolated_settings, tmp_path):
        """对应节已非默认值 → 旧档仅留档不导入（UnifiedConfig 为唯一真相源）。"""
        settings, _ = isolated_settings
        settings.config.autonomy.enabled = True  # 节非默认
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "autonomy_config.json").write_text(
            json.dumps({"enabled": False, "agent_id": "旧值"}), encoding="utf-8"
        )
        results = migrate_legacy_autonomy_configs(legacy_dir=str(legacy_dir))
        assert results["autonomy"] is False
        assert settings.config.autonomy.agent_id != "旧值"  # 未被旧值反向覆盖
        assert (legacy_dir / "autonomy_config.json.migrated").exists()

    def test_migrate_keeps_invalid_legacy_file_in_place(self, isolated_settings, tmp_path):
        """非法旧档（隐私红线越界）→ 跳过导入且保留现场，不损坏 UnifiedConfig。"""
        settings, _ = isolated_settings
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "dream_config.json").write_text(
            json.dumps({"store_raw_hr": True}), encoding="utf-8"  # 隐私红线 R6 越界
        )
        results = migrate_legacy_autonomy_configs(legacy_dir=str(legacy_dir))
        assert results["dream"] is False
        assert settings.config.dream.enabled is False  # 未被污染
        assert (legacy_dir / "dream_config.json").exists()  # 保留现场未改名
        assert not (legacy_dir / "dream_config.json.migrated").exists()

    def test_migrate_noop_without_legacy_files(self, isolated_settings, tmp_path):
        """无旧档时迁移为 no-op（幂等基线）。"""
        _, cfg_path = isolated_settings
        results = migrate_legacy_autonomy_configs(legacy_dir=str(tmp_path / "not_exists"))
        assert results == {"autonomy": False, "dream": False}
        assert not cfg_path.exists()

    def test_effective_config_resolution_prefers_legacy_then_settings(
        self, isolated_settings, tmp_path
    ):
        """装配配置解析序：旧档存在读旧档；旧档缺席读 UnifiedConfig 节。"""
        from server.autonomy.main import (
            _load_effective_autonomy_config,
            _load_effective_dream_config,
        )

        settings, _ = isolated_settings
        settings.config.autonomy.agent_id = "settings态"
        settings.config.dream.dream_temperature = 0.55

        # 旧档缺席 → settings 节生效
        cfg = _load_effective_autonomy_config(store_path=str(tmp_path / "empty"))
        assert cfg.agent_id == "settings态"
        assert cfg.store_path == str(tmp_path / "empty")
        dream_cfg = _load_effective_dream_config(store_path=str(tmp_path / "empty"))
        assert dream_cfg.dream_temperature == 0.55

        # 旧档存在 → 旧档优先（迁移前兼容 + 测试注入语义不变）
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "autonomy_config.json").write_text(
            json.dumps({"enabled": True, "agent_id": "旧档态"}), encoding="utf-8"
        )
        from server.autonomy._atomic_io import atomic_write_json
        from server.autonomy.dream.config import DreamConfig

        atomic_write_json(
            str(legacy_dir / "dream_config.json"),
            DreamConfig(dream_temperature=0.33).model_dump(),
        )
        assert _load_effective_autonomy_config(store_path=str(legacy_dir)).agent_id == "旧档态"
        assert (
            _load_effective_dream_config(store_path=str(legacy_dir)).dream_temperature == 0.33
        )


# ================================================================ ④ shutdown 清理断言
@pytest.mark.asyncio
class TestShutdownWiring:
    async def test_shutdown_stops_engines_and_flushes(self, monkeypatch):
        """patch 引擎 stop 与 flush_physio_store，触发清理函数断言全部被调。"""
        import server.autonomy.main as autonomy_main
        import server.main as server_main

        flush_calls = []
        monkeypatch.setattr(
            autonomy_main, "flush_physio_store", lambda: flush_calls.append(1)
        )
        services = SimpleNamespace(
            autonomy_engine=_FakeAutonomyEngine(),
            dream_engine=_FakeDreamEngine(),
        )
        await server_main._shutdown_dream_autonomy(services, logging.getLogger("test"))
        assert services.autonomy_engine.stop_calls == 1
        assert services.dream_engine.stop_calls == 1
        assert flush_calls == [1]

    async def test_shutdown_isolates_single_failure_and_flushes_last(self, monkeypatch):
        """单个引擎 stop 失败被隔离，其余清理与 flush 仍执行（flush 兜底最后）。"""
        import server.autonomy.main as autonomy_main
        import server.main as server_main

        flush_calls = []
        monkeypatch.setattr(
            autonomy_main, "flush_physio_store", lambda: flush_calls.append(1)
        )
        services = SimpleNamespace(
            autonomy_engine=_FakeAutonomyEngine(fail=True),
            dream_engine=_FakeDreamEngine(),
        )
        # 不应抛出任何异常
        await server_main._shutdown_dream_autonomy(services, logging.getLogger("test"))
        assert services.autonomy_engine.stop_calls == 1
        assert services.dream_engine.stop_calls == 1
        assert flush_calls == [1]

    async def test_shutdown_skips_missing_engines_but_flushes(self, monkeypatch):
        """引擎未装配（None）时跳过 stop，flush 仍兜底执行。"""
        import server.autonomy.main as autonomy_main
        import server.main as server_main

        flush_calls = []
        monkeypatch.setattr(
            autonomy_main, "flush_physio_store", lambda: flush_calls.append(1)
        )
        services = SimpleNamespace()
        await server_main._shutdown_dream_autonomy(services, logging.getLogger("test"))
        assert flush_calls == [1]


# ================================================================ ⑤ 契约镜像 + 热更新登记
class TestContractMirrorAndHotReload:
    def test_sections_mirror_engine_config_fields(self):
        """节模型与引擎侧配置逐字段同构（防双定义漂移）：字段名与默认值一致。"""
        from server.autonomy.config import AutonomyConfig
        from server.autonomy.dream.config import DreamConfig

        autonomy_engine = AutonomyConfig().model_dump()
        autonomy_section = AutonomySection().model_dump()
        assert set(autonomy_section) == set(autonomy_engine)
        for key, value in autonomy_engine.items():
            if isinstance(value, dict):
                assert set(autonomy_section[key]) == set(value), f"autonomy.{key} 子节漂移"
                continue
            assert autonomy_section[key] == value, f"autonomy.{key} 默认值漂移"

        dream_engine = DreamConfig().model_dump()
        dream_section = DreamSection().model_dump()
        assert set(dream_section) == set(dream_engine)
        for key, value in dream_engine.items():
            if isinstance(value, dict):
                assert set(dream_section[key]) == set(value), f"dream.{key} 子节漂移"
                continue
            assert dream_section[key] == value, f"dream.{key} 默认值漂移"

    def test_legacy_json_shapes_import_into_sections(self, tmp_path):
        """仓库真实旧档（若留档存在）可无损导入节模型（形状兼容证明）。"""
        base = Path(__file__).resolve().parents[1] / "server" / "autonomy" / "data"
        migrated_autonomy = base / "autonomy_config.json.migrated"
        if migrated_autonomy.exists():
            raw = json.loads(migrated_autonomy.read_text(encoding="utf-8"))
            AutonomySection.model_validate(raw)  # 不抛即形状兼容
        migrated_dream = base / "dream_config.json.migrated"
        if migrated_dream.exists():
            raw = json.loads(migrated_dream.read_text(encoding="utf-8"))
            DreamSection.model_validate(raw)

    def test_requires_restart_registered(self):
        """REQUIRES_RESTART 登记 autonomy/dream（读表结构：布尔值）。"""
        assert REQUIRES_RESTART.get("autonomy") is True
        assert REQUIRES_RESTART.get("dream") is True

    def test_unified_config_mounts_sections(self):
        """UnifiedConfig 根挂载两节（默认零侵入：均未启用）。"""
        cfg = UnifiedConfig()
        assert cfg.autonomy.enabled is False
        assert cfg.dream.enabled is False
        dump = cfg.model_dump()
        assert "autonomy" in dump and "dream" in dump
