"""config.update 白名单扩展测试（spec enhance-admin-telemetry T2）。

覆盖：
- ADMIN_CONFIG_UPDATE_WHITELIST 结构：llm/models 既有字段逐字保留（对照旧
  frozenset 内容清单）+ 新节（limits/logging/system/executor/autonomy/dream）在册
- config.update 扩展行为：limits 热改落盘回显、logging.level 热调钩子（root
  logger 级别真变且测后恢复）、executor 上界/负值/重启标注、autonomy/dream
  标量与深层路径、危险节参数化拒绝
替身策略参照 test_admin_model_context.py：FakeSettings 持真实配置节模型 +
monkeypatch server.config.get_settings + CacheSpy。

运行：python -m pytest tests/test_admin_config_whitelist.py -v
"""
import logging
from types import SimpleNamespace

import pytest

from server.core import cache as cache_mod
from server.core.admin.control_plane import (
    ADMIN_CONFIG_UPDATE_WHITELIST,
    _CONFIG_UPDATE_WHITELIST,
    AdminControlError,
    AdminControlPlane,
)
from server.config import (
    AutonomySection,
    DreamSection,
    ExecutorConfig,
    LimitsConfig,
    LLMConfig,
    LoggingConfig,
    ModelsConfig,
    SystemConfig,
)


class CacheSpy:
    """agent_config_cache 替身：记录 delete 调用。"""

    def __init__(self):
        self.deleted = []

    def delete(self, key):
        self.deleted.append(key)
        return True


class FakeSettings:
    """配置替身：各节用真实 pydantic 模型，save_config 只记标记不落盘。"""

    def __init__(self):
        self.config = SimpleNamespace(
            llm=LLMConfig(),
            models=ModelsConfig(),
            limits=LimitsConfig(),
            logging=LoggingConfig(),
            system=SystemConfig(),
            executor=ExecutorConfig(),
            autonomy=AutonomySection(),
            dream=DreamSection(),
        )
        self.saved = False

    def save_config(self):
        self.saved = True


@pytest.fixture
def env(monkeypatch):
    """统一测试环境：FakeSettings + 缓存 spy + 真实 AdminControlPlane。"""
    fake = FakeSettings()
    monkeypatch.setattr("server.config.get_settings", lambda: fake)
    spy = CacheSpy()
    monkeypatch.setattr(cache_mod, "agent_config_cache", spy)
    plane = AdminControlPlane(services=None, auth=None, cluster_bridge=None)
    return SimpleNamespace(fake=fake, spy=spy, plane=plane, monkeypatch=monkeypatch)


def _update(env, params):
    """经 dispatch 走 config.update 真实实现；AdminControlError 透传给断言。"""
    return env.plane.dispatch("update", "config", "r", "default", params)


# 旧版 frozenset 内容清单（spec enhance-cxfc-admin-and-integrate-dream 三原文，
# 重构后必须逐字保留——既有测试断言字段零丢失的对照基准）
_LEGACY_WHITELIST = frozenset(
    {f"llm.{f}" for f in ("provider", "model", "host", "port", "max_tokens", "temperature")}
    | {
        f"models.{slot}.{f}"
        for slot in ("main", "summary", "memory")
        for f in ("model", "max_tokens", "temperature", "host", "port")
    }
)


class TestWhitelistStructure:
    """白名单结构断言：既有字段零丢失 + 新节在册 + 危险面排除。"""

    def test_llm_fields_preserved(self):
        assert ADMIN_CONFIG_UPDATE_WHITELIST["llm"] == {
            "provider", "model", "host", "port", "max_tokens", "temperature",
        }

    def test_models_fields_preserved(self):
        assert ADMIN_CONFIG_UPDATE_WHITELIST["models"] == {
            f"{slot}.{f}"
            for slot in ("main", "summary", "memory")
            for f in ("model", "max_tokens", "temperature", "host", "port")
        }

    def test_legacy_flat_view_verbatim(self):
        # 旧 frozenset 内容清单逐字保留：旧名现为扩展后白名单的扁平派生视图，
        # 正确不变式为"旧清单 ⊆ 新视图"（llm/models 子集零丢失，结构等价断言
        # 由 test_llm_fields_preserved / test_models_fields_preserved 承担）
        assert _LEGACY_WHITELIST <= _CONFIG_UPDATE_WHITELIST
        # llm/models 域在新视图中无增无减（无通配扩张）
        assert {
            p for p in _CONFIG_UPDATE_WHITELIST if p.startswith(("llm.", "models."))
        } == _LEGACY_WHITELIST

    def test_limits_context_seven_fields(self):
        limits = ADMIN_CONFIG_UPDATE_WHITELIST["limits"]
        # context 7 字段在册
        assert limits >= {
            "context.max_messages", "context.window_size", "context.summary_threshold",
            "context.max_history", "context.conversation_max_messages",
            "context.conversation_recent_window", "context.chat_context_limit",
        }
        # memory 全字段在册（实读 MemoryLimitsConfig 16 字段）
        assert limits >= {
            "memory.max_memories", "memory.min_score_threshold",
            "memory.hybrid_search_limit", "memory.hybrid_search_min_score",
            "memory.vector_min_score", "memory.inject_memories_count",
            "memory.rag_search_limit", "memory.entity_extract_max_content",
            "memory.max_entities", "memory.max_relationships",
            "memory.entity_candidates", "memory.search_memories_limit",
            "memory.search_similar_threshold", "memory.search_similar_limit",
            "memory.chat_history_limit", "memory.memory_logs_limit",
        }

    def test_logging_system_executor_exact(self):
        assert ADMIN_CONFIG_UPDATE_WHITELIST["logging"] == {"level"}
        assert ADMIN_CONFIG_UPDATE_WHITELIST["system"] == {"debug"}
        # executor 显式 3 字段（其余 6 字段不放开，防通配误读）
        assert ADMIN_CONFIG_UPDATE_WHITELIST["executor"] == {
            "io_pool_size", "danmaku_concurrency", "interrupt_concurrency",
        }

    def test_autonomy_dream_scalar_deep_paths(self):
        auto = ADMIN_CONFIG_UPDATE_WHITELIST["autonomy"]
        # autonomy 顶层标量 + 子节深层路径在册
        assert {"enabled", "auto_start", "agent_id", "loop_interval_minutes", "store_path"} <= auto
        assert {"schedule.wake_time", "search.mcp_server_name",
                "budget.overspend_mode", "safety.post_rate_per_hour"} <= auto
        dream = ADMIN_CONFIG_UPDATE_WHITELIST["dream"]
        # dream 顶层标量 + 子节深层路径在册
        assert {"enabled", "model", "dream_temperature", "min_lucidity",
                "surface_probability"} <= dream
        assert {"trigger.probability", "physio.enabled",
                "sleep_confirmation.cooldown_seconds"} <= dream

    def test_list_and_privacy_fields_absent(self):
        auto = ADMIN_CONFIG_UPDATE_WHITELIST["autonomy"]
        dream = ADMIN_CONFIG_UPDATE_WHITELIST["dream"]
        # 列表字段不放开（标量节口径）
        assert "rss_sources" not in auto and "platforms" not in auto
        assert "permissions.allowed_actions" not in auto
        assert "schedule.quiet_windows" not in auto
        assert "schedule.quiet_windows" not in dream
        # 隐私红线 R6：原始心率禁止落盘，store_raw_hr 刻意排除
        assert "physio.store_raw_hr" not in dream

    def test_dangerous_sections_absent(self):
        # 结构性危险节不在册（白名单外既有路径 400）
        for sec in ("admin", "cluster", "database", "cors", "mcp_servers",
                    "gateway", "services"):
            assert sec not in ADMIN_CONFIG_UPDATE_WHITELIST
        # 敏感字段不在册
        assert "api_key" not in ADMIN_CONFIG_UPDATE_WHITELIST["llm"]


class TestLimitsContextUpdate:
    """limits.context/limits.memory：热改落盘 + 回显，无 ADDITIVE 标注。"""

    def test_chat_context_limit_update(self, env):
        out = _update(env, {"limits.context.chat_context_limit": 25})
        assert env.fake.config.limits.context.chat_context_limit == 25
        assert env.fake.saved is True
        assert "all_agents" in env.spy.deleted
        assert out["result"]["updated"] == ["limits.context.chat_context_limit"]
        # 热生效：无 hot_applied/restart_required/note ADDITIVE 标注
        assert "hot_applied" not in out["result"]
        assert "restart_required" not in out["result"]
        assert "note" not in out["result"]
        # requires_restart 为既有键，按登记表 limits=True 整节保守语义
        assert out["result"]["requires_restart"] == {"limits": True}

    def test_context_upper_bound_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"limits.context.max_messages": 200000})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
        # 拒绝后值不变、未落盘
        assert env.fake.config.limits.context.max_messages == 500
        assert env.fake.saved is False

    def test_memory_negative_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"limits.memory.max_memories": -1})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
        assert env.fake.config.limits.memory.max_memories == 30

    def test_memory_threshold_update(self, env):
        out = _update(env, {"limits.memory.min_score_threshold": 0.25})
        assert env.fake.config.limits.memory.min_score_threshold == 0.25
        assert out["result"]["updated"] == ["limits.memory.min_score_threshold"]


class TestLoggingLevelHotApply:
    """logging.level：落盘 + root logger 级别即时真变（测后恢复）。"""

    def test_level_change_hot_applied(self, env):
        root = logging.getLogger()
        old_level = root.level
        try:
            out = _update(env, {"logging.level": "DEBUG"})
            assert out["result"]["hot_applied"] is True
            assert root.level == logging.DEBUG
            assert env.fake.config.logging.level == "DEBUG"
            assert env.fake.saved is True
            # logging 不在 REQUIRES_RESTART 表 → 默认 False（level 走即时钩子）
            assert out["result"]["requires_restart"] == {"logging": False}
        finally:
            root.setLevel(old_level)

    def test_lowercase_level_normalized(self, env):
        root = logging.getLogger()
        old_level = root.level
        try:
            out = _update(env, {"logging.level": "warning"})
            assert out["result"]["hot_applied"] is True
            assert root.level == logging.WARNING
            assert env.fake.config.logging.level == "warning"
        finally:
            root.setLevel(old_level)

    def test_invalid_level_400(self, env):
        root = logging.getLogger()
        old_level = root.level
        try:
            with pytest.raises(AdminControlError) as ei:
                _update(env, {"logging.level": "VERBOSE"})
            assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
            # 拒绝后 root logger 级别不变、未落盘
            assert root.level == old_level
            assert env.fake.saved is False
        finally:
            root.setLevel(old_level)


class TestExecutorUpdate:
    """executor 显式 3 字段：上界/负值校验 + 重启语义标注。"""

    def test_io_pool_size_restart_required(self, env):
        out = _update(env, {"executor.io_pool_size": 16})
        assert env.fake.config.executor.io_pool_size == 16
        assert out["result"]["restart_required"] is True
        assert out["result"]["requires_restart"] == {"executor": True}
        assert env.fake.saved is True

    def test_over_upper_bound_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"executor.io_pool_size": 9999})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
        assert env.fake.config.executor.io_pool_size == 0
        assert env.fake.saved is False

    def test_negative_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"executor.danmaku_concurrency": -1})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
        assert env.fake.config.executor.danmaku_concurrency == 8

    def test_executor_other_fields_not_allowed(self, env):
        # 其余 6 字段显式不放开（防通配误读）
        for path in ("executor.asr_infer_workers", "executor.spk_engine_workers",
                     "executor.spk_inflight_max", "executor.tts_concurrency",
                     "executor.tts_backpressure_mode", "executor.asr_recv_queue_maxsize"):
            with pytest.raises(AdminControlError) as ei:
                _update(env, {path: 4})
            assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in str(ei.value)


class TestSystemDebug:
    """system.debug：布尔更新 + 越型拒绝 + 结构性字段不放开。"""

    def test_debug_bool_update(self, env):
        out = _update(env, {"system.debug": True})
        assert env.fake.config.system.debug is True
        # system 节已在册 REQUIRES_RESTART=False（可热更）
        assert out["result"]["requires_restart"] == {"system": False}

    def test_debug_non_bool_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"system.debug": "yes"})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
        assert env.fake.config.system.debug is False

    def test_system_other_fields_not_allowed(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"system.port": 9000})
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in str(ei.value)


class TestDangerousSectionsRejected:
    """结构性危险节保持拒绝（白名单外既有路径 400 既有错误码族）。"""

    @pytest.mark.parametrize("path,value", [
        ("admin.tokens", []),
        ("admin.bind", "0.0.0.0"),
        ("cluster.peers", ["n1"]),
        ("database.path", "data/evil.db"),
        ("cors.allow_origins", ["*"]),
        ("mcp_servers", []),
        ("gateway.host", "0.0.0.0"),
        ("services.asr.url", "http://evil"),
    ])
    def test_dangerous_paths_400(self, env, path, value):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {path: value})
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in str(ei.value)


class TestAutonomyDreamPaths:
    """autonomy/dream 标量深层路径：修改成功 + 枚举/格式/类型守卫。"""

    def test_autonomy_scalar_update(self, env):
        out = _update(env, {"autonomy.loop_interval_minutes": 30})
        assert env.fake.config.autonomy.loop_interval_minutes == 30
        # autonomy 命中 → 引擎侧同步提示 + 登记表需重启
        assert out["result"]["note"] == "引擎侧同步请调 PUT /autonomy/config | /dream/config"
        assert out["result"]["requires_restart"] == {"autonomy": True}

    def test_autonomy_deep_schedule_update(self, env):
        # 三层深层路径（autonomy.schedule.wake_time）经通用解析落点
        out = _update(env, {"autonomy.schedule.wake_time": "07:30"})
        assert env.fake.config.autonomy.schedule.wake_time == "07:30"
        assert "note" in out["result"]

    def test_autonomy_invalid_time_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"autonomy.schedule.wake_time": "99:99"})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
        assert env.fake.config.autonomy.schedule.wake_time == "08:00"

    def test_autonomy_bool_type_guard_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"autonomy.enabled": "yes"})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)
        assert env.fake.config.autonomy.enabled is False

    def test_autonomy_overspend_enum_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"autonomy.budget.overspend_mode": "yolo"})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)

    def test_autonomy_list_fields_not_allowed(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"autonomy.rss_sources": ["https://x"]})
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in str(ei.value)

    def test_dream_scalar_update(self, env):
        out = _update(env, {"dream.dream_temperature": 0.8})
        assert env.fake.config.dream.dream_temperature == 0.8
        assert out["result"]["note"] == "引擎侧同步请调 PUT /autonomy/config | /dream/config"

    def test_dream_deep_trigger_update(self, env):
        out = _update(env, {"dream.trigger.probability": 0.5})
        assert env.fake.config.dream.trigger.probability == 0.5

    def test_dream_ratio_bound_400(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"dream.min_lucidity": 1.5})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)

    def test_dream_physio_store_raw_hr_not_allowed(self, env):
        # 隐私红线 R6：store_raw_hr 不在白名单
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"dream.physio.store_raw_hr": True})
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in str(ei.value)

    def test_dream_sleep_confirmation_model_update(self, env):
        out = _update(env, {"dream.sleep_confirmation.model": "main"})
        assert env.fake.config.dream.sleep_confirmation.model == "main"


class TestBackwardCompat:
    """llm/models 既有行为零回归（经新白名单结构路径）。"""

    def test_llm_update_hot(self, env):
        out = _update(env, {"llm.temperature": 0.3})
        assert env.fake.config.llm.temperature == 0.3
        assert out["result"]["requires_restart"] == {"llm": False}
        assert "hot_applied" not in out["result"]

    def test_models_update_requires_restart(self, env):
        out = _update(env, {"models.main.max_tokens": 4096})
        assert env.fake.config.models.main.max_tokens == 4096
        assert out["result"]["requires_restart"] == {"models": True}

    def test_llm_api_key_rejected(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"llm.api_key": "sk-x"})
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in str(ei.value)

    def test_llm_port_field_unknown(self, env):
        # llm.port 白名单内但 LLMConfig 无该字段 → 字段存在性校验拒绝
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"llm.port": 11434})
        assert "ADMIN_CONFIG_FIELD_UNKNOWN" in str(ei.value)

    def test_unknown_model_slot_rejected(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"models.bogus.model": "m"})
        assert "ADMIN_CONFIG_FIELD_NOT_ALLOWED" in str(ei.value)

    def test_bool_temperature_rejected(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {"llm.temperature": True})
        assert "ADMIN_CONFIG_VALUE_TYPE" in str(ei.value)

    def test_empty_params_rejected(self, env):
        with pytest.raises(AdminControlError) as ei:
            _update(env, {})
        assert "ADMIN_CONFIG_UPDATE_EMPTY" in str(ei.value)
