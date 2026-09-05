"""CX-O-Autonomy P0-T2 骨架测试：配置默认/补齐/校验、管理器生命周期、builtin 直注装配。

覆盖：
1. config 默认值（对齐 autonomy_config.schema.json）+ 缺失字段自动补齐
2. config save/load 往返一致
3. 非法枚举（overspend_mode / action）与非法时间格式抛 ValueError
4. AutonomyManager 启停/暂停/恢复/紧急停止 + get_status 形状（jsonschema 校验对齐 state 契约）
5. setup_autonomy 在 enabled=False 时返回 None
6. enabled=True 时经真实 CXFCManager（临时 sqlite storage）装配后，工具直注
   ToolRegistry（category=="builtin"）、技能直注 SkillRegistry，且 /cxfc 插件列表
   不再出现 autonomy 条目（Task 6.1 去插件包装，双形态覆盖）
7. autonomy_get_status handler 可调用

运行：python -m pytest tests/test_autonomy_skeleton.py -q
"""
import json
from pathlib import Path

import pytest
from jsonschema import validate

from server.autonomy.action.social.poster import AutonomyPlatformNotWhitelistedError
from server.autonomy.config import AutonomyConfig, BudgetConfig, load_config, save_config
from server.autonomy.manager import AutonomyDisabledError, AutonomyManager
from server.autonomy.main import (
    AUTONOMY_CAPABILITIES,
    AUTONOMY_PLUGIN_ID,
    AUTONOMY_PLUGIN_NAME,
    SKILL_SPECS,
    TOOL_SPECS,
    get_autonomy_manager,
    get_handlers,
    setup_autonomy,
)

# 公共契约目录（public/）：c:\CX-O\public\
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"
STATE_SCHEMA = json.loads(
    (PUBLIC_DIR / "schema" / "autonomy_state.schema.json").read_text(encoding="utf-8")
)

ACTION_ENUM = [
    "sleep", "wait", "read_news", "search", "write_memory",
    "write_post", "start_live", "stop_live", "write_diary",
]


# ================================================================ ① 配置默认值 + 自动补齐
class TestConfigDefaults:
    def test_defaults_match_contract(self):
        cfg = AutonomyConfig()
        assert cfg.enabled is False
        assert cfg.auto_start is False
        assert cfg.agent_id == "default"
        assert cfg.loop_interval_minutes == 15
        assert cfg.rss_sources == []
        assert cfg.search.mcp_server_name == "free-search-mcp"
        assert cfg.search.fallback_rss is True
        assert cfg.schedule.wake_time == "08:00"
        assert cfg.schedule.sleep_time == "02:00"
        assert cfg.schedule.golden_start == "19:00"
        assert cfg.schedule.golden_end == "23:00"
        assert cfg.schedule.diary_time == "02:00"
        assert cfg.schedule.quiet_windows == []
        assert cfg.budget.daily_token_limit == 2000000
        assert cfg.budget.daily_llm_calls_limit == 0
        assert cfg.budget.cost_alert_threshold == 0.8
        assert cfg.budget.overspend_mode == "sleep"
        assert cfg.platforms == []
        assert cfg.permissions.allowed_actions == ACTION_ENUM
        assert cfg.permissions.blocked_actions == []
        assert cfg.safety.content_gate_enabled is True
        assert cfg.safety.persona_check_enabled is True
        assert cfg.safety.post_rate_per_hour == 5
        assert cfg.safety.user_online_sleep is True
        assert cfg.safety.leave_mode_authorize is True
        assert cfg.store_path == ""

    def test_missing_fields_auto_filled(self):
        # 契约无 required：空对象 → 全默认
        cfg = AutonomyConfig.model_validate({})
        assert cfg.enabled is False
        assert cfg.loop_interval_minutes == 15
        assert cfg.agent_id == "default"
        assert cfg.permissions.allowed_actions == ACTION_ENUM
        assert cfg.safety.post_rate_per_hour == 5
        assert cfg.budget.overspend_mode == "sleep"

        # 部分字段 → 其余自动补齐默认值
        partial = AutonomyConfig.model_validate(
            {"enabled": True, "loop_interval_minutes": 30, "platforms": ["weibo"]}
        )
        assert partial.enabled is True
        assert partial.loop_interval_minutes == 30
        assert partial.platforms == ["weibo"]
        assert partial.agent_id == "default"
        assert partial.budget.daily_token_limit == 2000000
        assert partial.schedule.wake_time == "08:00"


# ================================================================ ② save/load 往返一致
class TestConfigPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        cfg = AutonomyConfig(
            store_path=str(tmp_path),
            enabled=True,
            agent_id="测试人设",
            loop_interval_minutes=30,
            platforms=["weibo", "x"],
            budget=BudgetConfig(daily_token_limit=1000000, overspend_mode="low_cost"),
        )
        path = save_config(cfg)
        assert Path(path).exists()
        loaded = load_config(store_path=str(tmp_path))
        assert loaded == cfg

    def test_load_missing_file_returns_defaults(self, tmp_path):
        loaded = load_config(store_path=str(tmp_path / "not_exists"))
        assert loaded.enabled is False
        assert loaded.agent_id == "default"


# ================================================================ ③ 非法枚举/时间抛 ValueError
class TestConfigValidation:
    def test_invalid_overspend_mode_raises_valueerror(self):
        with pytest.raises(ValueError):
            AutonomyConfig(budget={"overspend_mode": "explode"})

    def test_invalid_action_raises_valueerror(self):
        with pytest.raises(ValueError):
            AutonomyConfig(permissions={"allowed_actions": ["delete_content"]})

    def test_invalid_time_format_raises_valueerror(self):
        with pytest.raises(ValueError):
            AutonomyConfig(schedule={"wake_time": "25:99"})

    def test_invalid_quiet_window_raises_valueerror(self):
        with pytest.raises(ValueError):
            AutonomyConfig(schedule={"quiet_windows": ["12:00"]})


# ================================================================ ④ AutonomyManager 生命周期
class TestManagerLifecycle:
    def test_disabled_raises(self):
        m = AutonomyManager()
        assert m.running is False
        with pytest.raises(AutonomyDisabledError):
            m.get_status()

    def test_enable_pause_resume_emergency_stop_and_status_shape(self):
        m = AutonomyManager()
        m.enable()
        assert m.running is True
        st = m.get_status()
        validate(instance=st, schema=STATE_SCHEMA)
        assert st["status"] == "running"
        assert st["motivations"] == {
            "curiosity": 0.2, "social_need": 0.2, "creative_drive": 0.2, "fatigue": 0.0,
        }
        assert st["daily_budget_used_tokens"] == 0

        # 暂停：running 置 False，状态仍可查询（不改变总开关）
        m.pause()
        assert m.running is False
        st = m.get_status()
        validate(instance=st, schema=STATE_SCHEMA)
        assert st["status"] == "paused"

        m.resume()
        assert m.running is True
        assert m.get_status()["status"] == "running"

        # 紧急停止：running 置 False，未启用 → get_status 抛 AutonomyDisabledError
        m.emergency_stop()
        assert m.running is False
        with pytest.raises(AutonomyDisabledError):
            m.get_status()


# ================================================================ ⑤ enabled=False → None
@pytest.mark.asyncio
async def test_setup_autonomy_disabled_returns_none(tmp_path):
    class FakeServices:
        def __init__(self):
            self.autonomy_manager = None

    services = FakeServices()
    cfg = AutonomyConfig(store_path=str(tmp_path), enabled=False)
    save_config(cfg)
    result = await setup_autonomy(services, store_path=str(tmp_path))
    assert result is None
    assert services.autonomy_manager is None
    assert get_autonomy_manager() is None


# ================================================================ ⑥⑦ enabled=True 直注装配 + handler
@pytest.mark.asyncio
async def test_setup_autonomy_enabled_registers_embedded_and_handler(tmp_path):
    from server.core.cxfc.manager import CXFCManager
    from server.core.tools.registry import ToolRegistry

    # 真实 CXFCManager + 临时 sqlite storage
    cxfc = CXFCManager(storage_path=str(tmp_path / "cxfc.db"))
    await cxfc._storage.init_db()
    tr = ToolRegistry()
    cxfc.set_tool_registry(tr)

    class FakeServices:
        def __init__(self):
            self.cxfc_manager = cxfc
            self.tool_registry = tr
            self.autonomy_manager = None

    services = FakeServices()
    cfg = AutonomyConfig(store_path=str(tmp_path), enabled=True)
    save_config(cfg)
    manager = await setup_autonomy(services, store_path=str(tmp_path))
    assert manager is not None
    assert services.autonomy_manager is manager

    # 去插件包装（Task 6.1）：插件列表不再出现 autonomy 条目（双形态覆盖）
    ids = {p.plugin_id for p in cxfc.get_plugins()}
    assert f"embedded_{AUTONOMY_PLUGIN_ID}" not in ids
    assert AUTONOMY_PLUGIN_ID not in ids

    # ⑥ 工具直注 ToolRegistry：全部 category=="builtin" 且 handler 已接线
    handlers = get_handlers()
    for spec in TOOL_SPECS:
        tool = tr.get_tool(spec["name"])
        assert tool is not None, f"工具 {spec['name']} 未注册"
        assert tool.category == "builtin"
        assert tool.function is handlers[spec["name"]]

    # ⑥ 技能直注 SkillRegistry：来源登记为 builtin（不再归属插件）
    skills = {s.name: s for s in cxfc.get_skill_registry().get_all_skills()}
    assert "autonomy_loop" in skills
    assert skills["autonomy_loop"].source_plugin_id == "builtin"

    # ⑦ autonomy_get_status handler 可调用（直接调用 + 经 ToolRegistry 分发）
    assert "autonomy_get_status" in handlers
    st = handlers["autonomy_get_status"]()
    validate(instance=st, schema=STATE_SCHEMA)
    assert st["status"] == "running"

    out = tr.call_tool("autonomy_get_status", {})
    assert out["success"] is True
    validate(instance=out["result"], schema=STATE_SCHEMA)

    # ⑦/P1-T8：read_news 已接线真实 handler（无 RSS 源时返回空列表）
    read_news = await handlers["autonomy_read_news"]()
    assert read_news == []

    # P2-T3：write_post 已接线真实 handler——测试配置 platforms 为空，
    # 平台不在白名单抛 AutonomyPlatformNotWhitelistedError（而非占位 NotImplementedError）
    with pytest.raises(AutonomyPlatformNotWhitelistedError):
        await handlers["autonomy_write_post"]("weibo", "草稿")
    # P3-T1：start_live / stop_live 已接线真实 handler——测试环境无电脑控制插件
    # 且无 llm_client：开播返回 prepared（脚本就绪未执行），下播返回 stopped
    # 且记忆写入降级（memory_manager 未注入 → summary_memory_id None）
    live_res = await handlers["autonomy_start_live"]("脚本")
    assert live_res["status"] == "prepared"
    stop_res = await handlers["autonomy_stop_live"]()
    assert stop_res["status"] == "stopped"
    assert stop_res["summary_memory_id"] is None

    # P1-T8：停用引擎后台循环任务，避免悬挂
    if getattr(services, "autonomy_engine", None) is not None:
        await services.autonomy_engine.stop()

    await cxfc.shutdown()


# ================================================================ 工具/技能规格完整性
class TestSpecs:
    def test_tool_specs_names_and_params(self):
        assert len(TOOL_SPECS) == 9
        names = [t["name"] for t in TOOL_SPECS]
        assert names == [
            "autonomy_get_status", "autonomy_read_news", "autonomy_search",
            "autonomy_write_memory", "autonomy_retrieve_memory", "autonomy_write_post",
            "autonomy_start_live", "autonomy_stop_live", "autonomy_write_diary",
        ]
        for t in TOOL_SPECS:
            assert t["description"]
            assert isinstance(t["parameters"], dict)
            assert t["parameters"].get("type") == "object"

    def test_skill_specs_has_autonomy_loop(self):
        assert any(s.get("name") == "autonomy_loop" and s.get("trigger_keywords") for s in SKILL_SPECS)
