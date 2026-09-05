"""server.core.admin.telemetry + 管理面三端点测试（spec enhance-admin-telemetry T1）。

覆盖：
- 四组快照形状断言（fake services：ws_manager 统计透传 / ASR 会话 / TTS 信号量 / 引擎缺失降级）
- groups 过滤（单组 / 多组 / 非法组忽略 / None 全量）
- psutil 缺失降级（cpu/memory None + "psutil": false）
- 引擎探测抛异常 → available:false 不 500
- AdminAuth 安全计数器（auth_fail / rate_limited / replay，独立锁，AdminDisabled 不计数）
- GET /admin/telemetry、GET /admin/config-whitelist、PUT /admin/logging/level 端点口径
- 三端点未注入 503 / 未认证 401 / 越权 403

运行：python -m pytest tests/test_admin_telemetry.py -v
"""
import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api.routers import admin as admin_router_mod
from server.core.admin import telemetry as telemetry_mod
from server.core.admin.auth import (
    AdminAuth,
    AdminAuthError,
    AdminDisabledError,
    AdminRateLimitedError,
    AdminReplayError,
)
from server.core.admin.control_plane import AdminControlError


class Box:
    """轻量属性容器（对齐 test_admin_control_plane.Box 模式）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _cfg(tokens=None, ttl=300, rps=1000.0):
    cfg = MagicMock()
    cfg.tokens = tokens or []
    cfg.request_id_ttl_sec = ttl
    cfg.rate_limit_per_sec = rps
    return cfg


def _tok(token, level="readonly"):
    return MagicMock(token=token, level=level)


def _fake_services(**overrides):
    """遥测采集替身容器：ws 统计已知值 + 各引擎槽位缺省 None（降级口径）。"""
    ws = MagicMock()
    ws.get_stats.return_value = {
        "total_connections": 2,
        "total_channels": 3,
        "channels": {"live": 2},
        "llm_count": 1,
        "client_count": 2,
    }
    svc = Box(
        ws_manager=ws,
        asr_service=Box(_stream_sessions={"c1": object(), "c2": object()}),
        tts_service=Box(_tts_limit=4, _tts_sem=asyncio.Semaphore(4)),
        admin_auth=None,
        autonomy_manager=None,
        dream_engine=None,
        tuner=None,
        meeting_coordinator=None,
        cxfc_manager=None,
    )
    for k, v in overrides.items():
        setattr(svc, k, v)
    return svc


# ---------------------------------------------------------------------------
# 采集函数：runtime 组
# ---------------------------------------------------------------------------


class TestCollectRuntime:
    def test_shape_full(self):
        out = asyncio.run(telemetry_mod.collect_runtime())
        assert out["available"] is True
        assert out["uptime_sec"] >= 0
        assert out["uptime_source"] in ("psutil", "module_import")
        # 异步上下文内 lag 探针产出 float
        assert isinstance(out["event_loop_lag_ms"], float)
        assert out["event_loop_lag_ms"] >= 0
        io = out["io_pool"]
        assert isinstance(io.get("max_workers"), int) and io["max_workers"] >= 1
        assert isinstance(io.get("active_threads"), int)
        assert io.get("queue_depth") is None or isinstance(io.get("queue_depth"), int)
        assert set(out["gc"]["counts"]) == {"gen0", "gen1", "gen2"}
        assert out["gc"]["totals"]["collections"] >= 0
        cm = out["cpu_memory"]
        # psutil 是否安装自适应断言（当前环境已安装 → True；缺失环境 → False）
        try:
            import psutil as _psutil  # noqa: F401

            assert cm["psutil"] is True
        except ImportError:
            assert cm["psutil"] is False
            assert cm["cpu_percent"] is None and cm["memory_percent"] is None

    def test_psutil_missing_degrade(self, monkeypatch):
        """psutil 缺失降级：cpu/memory 为 None + psutil:false + uptime 走模块基准。"""
        monkeypatch.setattr(telemetry_mod, "psutil", None)
        monkeypatch.setattr(telemetry_mod, "_psutil_process", None)  # 重置惰性句柄缓存
        out = asyncio.run(telemetry_mod.collect_runtime())
        cm = out["cpu_memory"]
        assert cm["psutil"] is False
        assert cm["cpu_percent"] is None
        assert cm["memory_percent"] is None
        assert out["uptime_source"] == "module_import"
        assert out["uptime_sec"] >= 0
        # 其余子项不受 psutil 缺失影响
        assert "error" not in out["gc"]
        assert out["io_pool"].get("max_workers", 0) >= 1


# ---------------------------------------------------------------------------
# 采集函数：connections 组
# ---------------------------------------------------------------------------


class TestCollectConnections:
    def test_shape_with_fakes(self):
        out = telemetry_mod.collect_connections(_fake_services())
        assert out["available"] is True
        ws = out["websocket"]
        assert ws["available"] is True
        assert ws["total_connections"] == 2
        assert ws["llm_count"] == 1
        assert out["asr_stream_sessions"] == {"available": True, "active": 2}
        # TTS 口径为信号量占用（无显式 Queue）：limit=4，未占用 → in_flight=0
        assert out["tts"]["available"] is True
        assert out["tts"]["limit"] == 4
        assert out["tts"]["in_flight"] == 0
        assert out["tts"]["locked"] is False
        assert out["vad"]["available"] is True
        assert out["vad"]["is_speaking"] is False
        vl = out["voice_latency"]
        assert vl["available"] is True
        assert isinstance(vl["summary"], dict)

    def test_tts_in_flight_occupancy(self):
        sem = asyncio.Semaphore(4)
        # 模拟占用 2 个 slot（acquire 不释放）
        async def _occupy():
            await sem.acquire()
            await sem.acquire()
        asyncio.run(_occupy())
        svc = _fake_services(tts_service=Box(_tts_limit=4, _tts_sem=sem))
        out = telemetry_mod.collect_connections(svc)
        assert out["tts"]["in_flight"] == 2
        assert out["tts"]["locked"] is False

    def test_missing_services_degrade(self):
        svc = Box(ws_manager=None, asr_service=None, tts_service=None)
        out = telemetry_mod.collect_connections(svc)
        assert out["available"] is True
        assert out["asr_stream_sessions"]["available"] is False
        assert out["tts"]["available"] is False

    def test_ws_stats_exception_degrades(self):
        ws = MagicMock()
        ws.get_stats.side_effect = RuntimeError("ws exploded")
        out = telemetry_mod.collect_connections(_fake_services(ws_manager=ws))
        assert out["websocket"]["available"] is False
        assert "ws exploded" in out["websocket"]["error"]


# ---------------------------------------------------------------------------
# 采集函数：engines 组
# ---------------------------------------------------------------------------


class TestCollectEngines:
    def test_all_missing_degrade(self):
        out = telemetry_mod.collect_engines(_fake_services())
        for name in ("autonomy", "dream", "tuner", "meeting", "cxfc"):
            assert out[name]["available"] is False
            assert out[name]["error"]
            assert out[name]["enabled"] is False
            assert out[name]["running"] is False

    def test_autonomy_running(self):
        auto = Box(
            enabled=True, running=True, status="running",
            get_status=lambda: {"status": "running", "last_action": None},
        )
        out = telemetry_mod.collect_engines(_fake_services(autonomy_manager=auto))
        assert out["autonomy"]["available"] is True
        assert out["autonomy"]["enabled"] is True
        assert out["autonomy"]["running"] is True
        assert out["autonomy"]["detail"]["status"] == "running"

    def test_autonomy_disabled_skips_get_status(self):
        """enabled=False 时直读属性，不调 get_status（其未启用路径会抛异常）。"""
        calls = []

        def _boom():
            calls.append(1)
            raise RuntimeError("未启用不应调用 get_status")

        auto = Box(enabled=False, running=False, status="paused", get_status=_boom)
        out = telemetry_mod.collect_engines(_fake_services(autonomy_manager=auto))
        assert out["autonomy"]["available"] is True
        assert out["autonomy"]["enabled"] is False
        assert out["autonomy"]["running"] is False
        assert calls == []

    def test_dream_probe(self):
        dream = Box(get_status=lambda: {"status": "idle", "enabled": True, "stats": {}})
        out = telemetry_mod.collect_engines(_fake_services(dream_engine=dream))
        assert out["dream"]["available"] is True
        assert out["dream"]["enabled"] is True
        assert out["dream"]["running"] is True

    def test_dream_disabled_status(self):
        dream = Box(get_status=lambda: {"status": "disabled", "enabled": False})
        out = telemetry_mod.collect_engines(_fake_services(dream_engine=dream))
        assert out["dream"]["running"] is False

    def test_dream_exception_degrades_not_500(self):
        def _boom():
            raise RuntimeError("dream exploded")

        dream = Box(get_status=_boom)
        out = telemetry_mod.collect_engines(_fake_services(dream_engine=dream))
        assert out["dream"]["available"] is False
        assert "dream exploded" in out["dream"]["error"]

    def test_meeting_active_rooms(self):
        coord = Box(rooms={"r1": object(), "r2": object()})
        out = telemetry_mod.collect_engines(_fake_services(meeting_coordinator=coord))
        assert out["meeting"]["available"] is True
        assert out["meeting"]["running"] is True
        assert out["meeting"]["detail"]["active_rooms"] == 2

    def test_cxfc_heartbeat_and_plugins(self):
        task = MagicMock()
        task.done.return_value = False
        cxfc = Box(_heartbeat_task=task, _plugins={"p1": object()})
        out = telemetry_mod.collect_engines(_fake_services(cxfc_manager=cxfc))
        assert out["cxfc"]["available"] is True
        assert out["cxfc"]["running"] is True
        assert out["cxfc"]["detail"]["plugins"] == 1


# ---------------------------------------------------------------------------
# 采集函数：security 组
# ---------------------------------------------------------------------------


class TestCollectSecurity:
    def test_counters_shape(self):
        auth = AdminAuth(_cfg(tokens=[_tok("t", "operator")]))
        out = telemetry_mod.collect_security(_fake_services(admin_auth=auth))
        assert out["available"] is True
        assert out["counters"] == {
            "available": True,
            "auth_fail_count": 0,
            "rate_limited_count": 0,
            "replay_count": 0,
        }
        # 审计摘要恒为列表（真实 data/admin_audit.jsonl 可能存在或为空）
        assert isinstance(out["recent_audit"], list)

    def test_no_auth_degrades(self):
        out = telemetry_mod.collect_security(_fake_services(admin_auth=None))
        assert out["counters"]["available"] is False
        assert out["counters"]["error"]

    def test_auth_without_getter_degrades(self):
        out = telemetry_mod.collect_security(_fake_services(admin_auth=object()))
        assert out["counters"]["available"] is False


# ---------------------------------------------------------------------------
# collect_all：groups 过滤 + 单组异常隔离
# ---------------------------------------------------------------------------


class TestCollectAll:
    def test_none_returns_all_groups(self):
        out = asyncio.run(telemetry_mod.collect_all(_fake_services(), None))
        assert set(out.keys()) == {"runtime", "connections", "engines", "security"}

    def test_empty_string_returns_all_groups(self):
        out = asyncio.run(telemetry_mod.collect_all(_fake_services(), ""))
        assert set(out.keys()) == {"runtime", "connections", "engines", "security"}

    def test_single_group(self):
        out = asyncio.run(telemetry_mod.collect_all(_fake_services(), ["security"]))
        assert set(out.keys()) == {"security"}

    def test_multi_groups(self):
        out = asyncio.run(telemetry_mod.collect_all(_fake_services(), "runtime,engines"))
        assert set(out.keys()) == {"runtime", "engines"}

    def test_invalid_groups_ignored(self):
        out = asyncio.run(telemetry_mod.collect_all(_fake_services(), "runtime,bogus"))
        assert set(out.keys()) == {"runtime"}
        # 全部非法 → 忽略后为空结果（不静默回退全量）
        out2 = asyncio.run(telemetry_mod.collect_all(_fake_services(), "bogus1,bogus2"))
        assert out2 == {}

    def test_security_group_runs_offloop(self):
        """security 组含文件 IO，经 to_thread 包裹仍可正常返回。"""
        auth = AdminAuth(_cfg(tokens=[]))
        out = asyncio.run(telemetry_mod.collect_all(_fake_services(admin_auth=auth), ["security"]))
        assert out["security"]["counters"]["available"] is True


# ---------------------------------------------------------------------------
# AdminAuth 安全计数器（ADDITIVE，独立锁）
# ---------------------------------------------------------------------------


class TestSecurityCounters:
    def test_auth_fail_counts(self):
        auth = AdminAuth(_cfg(tokens=[_tok("a", "readonly")]))
        with pytest.raises(AdminAuthError):
            auth.authenticate("wrong-token")
        assert auth.get_security_counters()["auth_fail_count"] == 1
        # 成功认证不计数
        assert auth.authenticate("a") == "readonly"
        assert auth.get_security_counters()["auth_fail_count"] == 1

    def test_disabled_path_not_counted(self):
        """AdminDisabledError 路径不计数（显式设计声明）。"""
        auth = AdminAuth(_cfg(tokens=[]))
        with pytest.raises(AdminDisabledError):
            auth.authenticate("x")
        c = auth.get_security_counters()
        assert c["auth_fail_count"] == 0
        assert c["rate_limited_count"] == 0
        assert c["replay_count"] == 0

    def test_rate_limited_counts_and_still_raises(self):
        auth = AdminAuth(_cfg(tokens=[], rps=1))
        auth.check_rate_limit()  # 消耗唯一令牌
        with pytest.raises(AdminRateLimitedError):
            auth.check_rate_limit()
        assert auth.get_security_counters()["rate_limited_count"] == 1
        # 既有 429 行为不变：继续抛限流异常且计数递增
        with pytest.raises(AdminRateLimitedError):
            auth.check_rate_limit()
        assert auth.get_security_counters()["rate_limited_count"] == 2

    def test_replay_counts(self):
        auth = AdminAuth(_cfg(tokens=[]))
        auth.check_replay("rid-1")
        with pytest.raises(AdminReplayError):
            auth.check_replay("rid-1")
        assert auth.get_security_counters()["replay_count"] == 1
        # 不同 request_id 正常通过不计数
        auth.check_replay("rid-2")
        assert auth.get_security_counters()["replay_count"] == 1

    def test_counters_return_copies(self):
        auth = AdminAuth(_cfg(tokens=[]))
        snap = auth.get_security_counters()
        snap["auth_fail_count"] = 999
        assert auth.get_security_counters()["auth_fail_count"] == 0


# ---------------------------------------------------------------------------
# 端点：GET /admin/telemetry
# ---------------------------------------------------------------------------

_AUTH = {"Authorization": "Bearer super-token"}
_READONLY_AUTH = {"Authorization": "Bearer ro-token"}


class _FakePlane:
    """control_plane 替身：记录 dispatch 调用（logging 端点生效路径断言用）。"""

    def __init__(self):
        self.calls = []
        self.fail = False

    def dispatch(self, action, target, request_id, agent_id="default", params=None):
        self.calls.append(
            {"action": action, "target": target, "request_id": request_id, "params": params}
        )
        if self.fail:
            raise AdminControlError("ADMIN_CONFIG_FIELD_NOT_ALLOWED: logging.level（白名单外字段）")
        return {
            "action": action,
            "target": target,
            "ok": True,
            "result": {"updated": sorted(params.keys()), "requires_restart": {}},
        }


_RESET_GLOBALS = (
    "_admin_auth", "_control_plane", "_manifest",
    "_instance_registry", "_cluster_bridge", "_services",
)


def _reset_admin_globals():
    for name in _RESET_GLOBALS:
        setattr(admin_router_mod, name, None)


@pytest.fixture
def cx_a_client(monkeypatch):
    """注入 CX-A 运行时：真 AdminAuth（双 token）+ 假 control_plane + 假 services。"""
    auth = AdminAuth(
        _cfg(tokens=[_tok("super-token", "superadmin"), _tok("ro-token", "readonly")])
    )
    plane = _FakePlane()
    services = _fake_services(admin_auth=auth)
    admin_router_mod.inject_admin_runtime(auth, plane, MagicMock(), None, None, services)
    # 隔离审计写（不触真实 data/admin_audit.jsonl）
    monkeypatch.setattr(admin_router_mod, "audit_now", lambda *a, **k: {"id": "noop"})
    app = FastAPI()
    app.include_router(admin_router_mod.router)
    try:
        yield TestClient(app, raise_server_exceptions=False), auth, plane
    finally:
        _reset_admin_globals()


class TestTelemetryEndpoint:
    def test_full_snapshot_200(self, cx_a_client):
        c, _, _ = cx_a_client
        r = c.get("/admin/telemetry", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "success"
        assert set(body["telemetry"].keys()) == {"runtime", "connections", "engines", "security"}
        # connections 组透传已知 ws 统计
        assert body["telemetry"]["connections"]["websocket"]["total_connections"] == 2
        # engines 组五项齐全
        assert set(body["telemetry"]["engines"].keys()) >= {
            "autonomy", "dream", "tuner", "meeting", "cxfc",
        }

    def test_groups_filter_query(self, cx_a_client):
        c, _, _ = cx_a_client
        r = c.get("/admin/telemetry", headers=_AUTH, params={"groups": "runtime,engines"})
        assert r.status_code == 200
        assert set(r.json()["telemetry"].keys()) == {"runtime", "engines"}

    def test_unauthenticated_401(self, cx_a_client):
        c, _, _ = cx_a_client
        assert c.get("/admin/telemetry").status_code == 401
        assert c.get("/admin/telemetry", headers={"Authorization": "Bearer wrong"}).status_code == 401

    def test_readonly_allowed(self, cx_a_client):
        c, _, _ = cx_a_client
        r = c.get("/admin/telemetry", headers=_READONLY_AUTH)
        assert r.status_code == 200

    def test_not_injected_503(self):
        _reset_admin_globals()
        app = FastAPI()
        app.include_router(admin_router_mod.router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/admin/telemetry", headers=_AUTH)
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# 端点：GET /admin/config-whitelist
# ---------------------------------------------------------------------------


class TestConfigWhitelistEndpoint:
    def test_adaptive_whitelist_presence(self, cx_a_client):
        """T2 自适应：常量已合入 → 白名单映射含 llm/models 键；未合入 → available:false 占位。"""
        c, _, _ = cx_a_client
        from server.core.admin import control_plane as cp_mod

        r = c.get("/admin/config-whitelist", headers=_AUTH)
        assert r.status_code == 200
        body = r.json()
        if getattr(cp_mod, "ADMIN_CONFIG_UPDATE_WHITELIST", None):
            assert body["available"] is True
            assert "llm" in body["whitelist"]
            assert "models" in body["whitelist"]
            assert body["rejected_sections"]
            assert body["notes"]
        else:
            # T2 未完成：模块级 getattr 返回 None → available:false 占位而非 500
            assert body["available"] is False
            assert body["note"]

    def test_readonly_allowed(self, cx_a_client):
        c, _, _ = cx_a_client
        r = c.get("/admin/config-whitelist", headers=_READONLY_AUTH)
        assert r.status_code == 200

    def test_unauthenticated_401(self, cx_a_client):
        c, _, _ = cx_a_client
        assert c.get("/admin/config-whitelist").status_code == 401

    def test_not_injected_503(self):
        _reset_admin_globals()
        app = FastAPI()
        app.include_router(admin_router_mod.router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get("/admin/config-whitelist", headers=_AUTH)
        assert r.status_code == 503


# ---------------------------------------------------------------------------
# 端点：PUT /admin/logging/level
# ---------------------------------------------------------------------------


class TestLoggingLevelEndpoint:
    def test_hot_apply_debug(self, cx_a_client):
        c, _, plane = cx_a_client
        root = logging.getLogger()
        prev = root.getEffectiveLevel()
        try:
            r = c.put("/admin/logging/level", headers=_AUTH, json={"level": "DEBUG"})
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "success"
            assert body["hot_applied"] is True
            assert body["level"] == "DEBUG"
            # root logger 级别真变
            assert root.getEffectiveLevel() == logging.DEBUG
            assert body["previous_level"] == logging.getLevelName(prev)
            # 生效路径经 config.update 通道（落盘+缓存语义统一）
            assert plane.calls
            assert plane.calls[0]["action"] == "update"
            assert plane.calls[0]["target"] == "config"
            assert plane.calls[0]["params"] == {"logging.level": "DEBUG"}
        finally:
            root.setLevel(prev)

    def test_lowercase_normalized(self, cx_a_client):
        c, _, _ = cx_a_client
        root = logging.getLogger()
        prev = root.getEffectiveLevel()
        try:
            r = c.put("/admin/logging/level", headers=_AUTH, json={"level": "info"})
            assert r.status_code == 200
            assert r.json()["level"] == "INFO"
            assert root.getEffectiveLevel() == logging.INFO
        finally:
            root.setLevel(prev)

    def test_invalid_level_400(self, cx_a_client):
        c, _, plane = cx_a_client
        r = c.put("/admin/logging/level", headers=_AUTH, json={"level": "TRACE"})
        assert r.status_code == 400
        assert plane.calls == []

    def test_dispatch_failure_400(self, cx_a_client):
        """config.update 白名单拒绝（T2 未合入等场景）→ 400 不 hot apply。"""
        c, _, plane = cx_a_client
        plane.fail = True
        root = logging.getLogger()
        prev = root.getEffectiveLevel()
        try:
            r = c.put("/admin/logging/level", headers=_AUTH, json={"level": "ERROR"})
            assert r.status_code == 400
            # 失败路径不切换 root logger
            assert root.getEffectiveLevel() == prev
        finally:
            plane.fail = False
            root.setLevel(prev)

    def test_readonly_forbidden_403(self, cx_a_client):
        c, _, plane = cx_a_client
        r = c.put(
            "/admin/logging/level", headers=_READONLY_AUTH, json={"level": "DEBUG"}
        )
        assert r.status_code == 403
        assert plane.calls == []

    def test_unauthenticated_401(self, cx_a_client):
        c, _, _ = cx_a_client
        assert c.put("/admin/logging/level", json={"level": "DEBUG"}).status_code == 401

    def test_not_injected_503(self):
        _reset_admin_globals()
        app = FastAPI()
        app.include_router(admin_router_mod.router)
        c = TestClient(app, raise_server_exceptions=False)
        r = c.put("/admin/logging/level", headers=_AUTH, json={"level": "DEBUG"})
        assert r.status_code == 503
