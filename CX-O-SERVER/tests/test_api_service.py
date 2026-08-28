"""
server/api/routers/service.py 与 server/api/routers/stats.py 单元测试
服务路由的纯函数（配置合并/验证/精度）与统计路由
"""
import asyncio
import os
import threading
import time
import types
from unittest.mock import MagicMock

import psutil
import pytest
from fastapi import HTTPException

import server.api.routers.service as svc
import server.api.routers.stats as stats_mod
from server.api.routers.service import (
    _apply_config_updates,
    get_service_status,
    start_service,
    stop_service,
    validate_service_config,
    ServiceConfig,
)


# --------------------------------------------------------------------------- #
# _apply_config_updates —— 多向量后端配置合并
# --------------------------------------------------------------------------- #
class TestApplyConfigUpdates:
    def test_chroma_backend(self):
        cur = {}
        out = _apply_config_updates(cur, {
            "vector": {"backend": "chroma", "db_path": "/x/db", "collection_name": "c", "vector_size": 512},
        })
        assert out["memory"]["vector_backend"] == "chroma"
        assert out["memory"]["chroma"]["db_path"] == "/x/db"
        assert out["memory"]["chroma"]["collection_name"] == "c"
        assert out["memory"]["chroma"]["vector_size"] == 512

    def test_milvus_lite_backend(self):
        out = _apply_config_updates({}, {"vector": {"backend": "milvus_lite", "db_path": "/x/m", "vector_size": 256}})
        assert out["memory"]["vector_backend"] == "milvus_lite"
        assert out["memory"]["milvus_lite"]["db_path"] == "/x/m"
        assert out["memory"]["milvus_lite"]["vector_size"] == 256

    def test_weaviate_backend(self):
        out = _apply_config_updates({}, {"vector": {"backend": "weaviate", "weaviate_host": "h", "weaviate_port": 9000}})
        assert out["memory"]["vector_backend"] == "weaviate"
        # 第五轮 H3：写键映射为 UnifiedConfig.WeaviateConfig 真实字段 host/port
        assert out["memory"]["weaviate"]["host"] == "h"
        assert out["memory"]["weaviate"]["port"] == 9000
        assert out["memory"]["weaviate"]["embedded"] is False

    def test_weaviate_embedded_backend(self):
        out = _apply_config_updates(
            {}, {"vector": {"backend": "weaviate_embedded", "weaviate_host": "h", "weaviate_port": 9000}}
        )
        assert out["memory"]["vector_backend"] == "weaviate_embedded"
        assert out["memory"]["weaviate"]["host"] == "h"
        assert out["memory"]["weaviate"]["port"] == 9000
        assert out["memory"]["weaviate"]["embedded"] is True

    def test_qdrant_backend(self):
        out = _apply_config_updates({}, {"vector": {"backend": "qdrant", "qdrant_host": "q", "qdrant_port": 6333}})
        assert out["memory"]["vector_backend"] == "qdrant"
        assert out["memory"]["qdrant"]["qdrant_host"] == "q"
        assert out["memory"]["qdrant"]["qdrant_port"] == 6333

    def test_models_and_llm_params(self):
        out = _apply_config_updates({}, {"models": {"main": 1}, "llm_params": {"t": 0.7}})
        assert out["models"] == {"main": 1}
        assert out["llm_params"] == {"t": 0.7}

    def test_system_merge(self):
        out = _apply_config_updates({"system": {"host": "0.0.0.0"}}, {"system": {"port": 9000}})
        assert out["system"]["host"] == "0.0.0.0"
        assert out["system"]["port"] == 9000

    def test_system_explicit_keys(self):
        out = _apply_config_updates({}, {"host": "127.0.0.1", "port": 8001, "use_conda": False})
        assert out["system"]["host"] == "127.0.0.1"
        assert out["system"]["port"] == 8001
        assert out["system"]["use_conda"] is False

    def test_unknown_backend_ignored(self):
        out = _apply_config_updates({}, {"vector": {"backend": "unknown", "host": "x"}})
        assert out["memory"]["vector_backend"] == "unknown"

    def test_no_memory_key_preserved(self):
        out = _apply_config_updates({}, {"models": {"a": 1}})
        assert "memory" not in out


# --------------------------------------------------------------------------- #
# validate_service_config —— 命令注入防护
# --------------------------------------------------------------------------- #
class TestValidateServiceConfig:
    def test_valid(self):
        validate_service_config(ServiceConfig(host="0.0.0.0", port=8000, log_level="info"))

    def test_valid_custom_ip(self):
        validate_service_config(ServiceConfig(host="192.168.1.10", port=8080, log_level="debug"))

    def test_invalid_ip(self):
        with pytest.raises(HTTPException) as ex:
            validate_service_config(ServiceConfig(host="999.999.999.999", port=8000))
        assert ex.value.status_code == 400
        assert "Invalid host" in str(ex.value.detail)

    def test_invalid_host_format(self):
        with pytest.raises(HTTPException):
            validate_service_config(ServiceConfig(host="evil.com", port=8000))

    def test_port_zero(self):
        with pytest.raises(HTTPException) as ex:
            validate_service_config(ServiceConfig(host="0.0.0.0", port=0))
        assert "Invalid port" in str(ex.value.detail)

    def test_port_too_high(self):
        with pytest.raises(HTTPException):
            validate_service_config(ServiceConfig(host="0.0.0.0", port=70000))

    def test_invalid_log_level(self):
        with pytest.raises(HTTPException) as ex:
            validate_service_config(ServiceConfig(host="0.0.0.0", port=8000, log_level="verbose"))
        assert "Invalid log_level" in str(ex.value.detail)


# --------------------------------------------------------------------------- #
# get_conda_python_path / get_conda_activate_script
# --------------------------------------------------------------------------- #
class TestCondaPaths:
    def test_no_conda(self, monkeypatch):
        monkeypatch.setattr(svc, "get_project_root", lambda: "/nonexistent")
        assert svc.get_conda_python_path() is None
        assert svc.get_conda_activate_script() is None

    def test_finds_python(self, monkeypatch, tmp_path):
        monkeypatch.setattr(svc, "get_project_root", lambda: str(tmp_path))
        py = tmp_path / "Miniconda3" / "python.exe"
        py.parent.mkdir(parents=True)
        py.write_bytes(b"")
        assert svc.get_conda_python_path() == str(py)


# --------------------------------------------------------------------------- #
# /service/startup-command 路径选择
# --------------------------------------------------------------------------- #
class TestGetStartupCommand:
    @pytest.mark.asyncio
    async def test_conda_available(self, monkeypatch):
        monkeypatch.setattr(svc, "get_conda_python_path", lambda: "/opt/conda/bin/python")
        out = await svc.get_startup_command(use_conda=True)
        assert out["use_conda"] is True
        assert out["conda_available"] is True
        assert out["command"] == "/opt/conda/bin/python"
        assert "-m" in out["args"] and "uvicorn" in out["args"]

    @pytest.mark.asyncio
    async def test_conda_unavailable_falls_system(self, monkeypatch):
        monkeypatch.setattr(svc, "get_conda_python_path", lambda: None)
        out = await svc.get_startup_command(use_conda=True)
        assert out["conda_available"] is False


# --------------------------------------------------------------------------- #
# /service/environment
# --------------------------------------------------------------------------- #
class TestEnvironmentInfo:
    @pytest.mark.asyncio
    async def test_returns_platform(self, monkeypatch):
        monkeypatch.setattr(svc, "get_conda_python_path", lambda: None)
        out = await svc.get_environment_info()
        assert out["status"] == "success"
        assert out["environment"]["conda_available"] is False
        assert "platform" in out["environment"]


# --------------------------------------------------------------------------- #
# /service/config 与 /config/gateway
# --------------------------------------------------------------------------- #
class TestServiceConfigRoutes:
    @pytest.mark.asyncio
    async def test_gateway_config(self, monkeypatch):
        out = await svc.get_gateway_config()
        assert out["status"] == "success"
        assert out["config"]["status"] == "集成"
        assert "ws://127.0.0.1:8000/ws" in out["config"]["url"]


# --------------------------------------------------------------------------- #
# stats router
# --------------------------------------------------------------------------- #
class TestStatsRouter:
    def test_returns_counts(self):
        # stats 路由的 HTTPException 依赖真实 memory_mgr，此处仅验证模块可导入
        assert hasattr(stats_mod, "get_system_stats")


# --------------------------------------------------------------------------- #
# E7/E8/E16 修复回归 —— start 临界区原子性 / stop 兜底 cwd 防误杀 / 端口回读
# （全部 mock subprocess.Popen 与 psutil，不真实启动/终止任何进程）
# --------------------------------------------------------------------------- #
class _FakePopenProc:
    """subprocess.Popen 替身返回的伪进程对象。"""

    def __init__(self, pid: int):
        self.pid = pid


class _IterProc:
    """psutil.process_iter 替身进程（仅暴露 stop 兜底扫描用到的接口）。"""

    def __init__(self, pid, cmdline, cwd=None, cwd_error=None):
        self.pid = pid
        self.info = {"pid": pid, "name": "python", "cmdline": cmdline}
        self._cwd = cwd
        self._cwd_error = cwd_error

    def cwd(self):
        if self._cwd_error is not None:
            raise self._cwd_error
        return self._cwd


def _make_fake_psutil(running=True, iter_procs=None):
    """构造 svc.psutil 替身：隔离真实进程枚举/定位/终止。"""

    def fake_process(pid):
        p = MagicMock()
        p.pid = pid
        p.is_running.return_value = running
        p.create_time.return_value = time.time() - 100
        p.cmdline.return_value = ["python", "-m", "uvicorn", "server.main:app"]
        return p

    return types.SimpleNamespace(
        Process=fake_process,
        Error=psutil.Error,
        NoSuchProcess=psutil.NoSuchProcess,
        AccessDenied=psutil.AccessDenied,
        TimeoutExpired=psutil.TimeoutExpired,
        process_iter=lambda *a, **k: list(iter_procs or []),
    )


def _patch_start_env(monkeypatch, fake_psutil):
    """隔离 start_service 的外部效应：Popen/日志文件/pidfile/conda 探测。"""
    popen_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append({"cmd": list(cmd), "kwargs": kwargs})
        return _FakePopenProc(pid=1000 + len(popen_calls))

    monkeypatch.setattr(svc.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(svc, "_open_backend_log_file", lambda root_dir: (None, None))
    monkeypatch.setattr(svc, "_write_pidfile", lambda pid: None)
    monkeypatch.setattr(svc, "get_conda_python_path", lambda: None)
    monkeypatch.setattr(svc, "get_conda_activate_script", lambda: None)
    monkeypatch.setattr(svc, "psutil", fake_psutil)
    return popen_calls


@pytest.fixture()
def _svc_globals_reset():
    """保存/恢复 service 模块全局进程状态，测试间互不污染。"""
    saved = (
        svc._backend_process,
        svc._backend_port,
        svc._backend_log_handle,
        svc._backend_log_path,
    )
    svc._backend_process = None
    svc._backend_port = None
    svc._backend_log_handle = None
    svc._backend_log_path = None
    yield
    (
        svc._backend_process,
        svc._backend_port,
        svc._backend_log_handle,
        svc._backend_log_path,
    ) = saved


class TestStartCriticalSectionAtomicity:
    """E7：已运行检查与 Popen 同锁——重复/并发 start 不得产生双实例。"""

    _CFG = {"host": "127.0.0.1", "port": 8123, "use_conda": False}

    @pytest.mark.asyncio
    async def test_second_start_rejected_no_double_popen(self, monkeypatch, _svc_globals_reset):
        popen_calls = _patch_start_env(monkeypatch, _make_fake_psutil(running=True))
        cfg = ServiceConfig(**self._CFG)

        out1 = await start_service(cfg)
        assert out1["status"] == "success"
        assert len(popen_calls) == 1

        with pytest.raises(HTTPException) as ex:
            await start_service(cfg)
        assert ex.value.status_code == 400
        assert "already running" in str(ex.value.detail)
        # Popen 不得被第二次调用——检查与 Popen 处于同一临界区
        assert len(popen_calls) == 1

    @pytest.mark.asyncio
    async def test_in_lock_check_rejects_before_popen(self, monkeypatch, _svc_globals_reset):
        """模拟 TOCTOU：预检通过后、进入临界区前，另一线程已完成注册——
        锁内复查必须拒绝，且拒绝发生在 Popen 之前（验证检查与 Popen 同锁）。"""
        popen_calls = _patch_start_env(monkeypatch, _make_fake_psutil(running=True))

        live = MagicMock()
        gbp_calls = {"n": 0}

        def fake_get_backend_process():
            gbp_calls["n"] += 1
            return None if gbp_calls["n"] == 1 else live  # 预检放行，锁内复查命中

        monkeypatch.setattr(svc, "get_backend_process", fake_get_backend_process)
        # 预置"已被另一线程登记"的进程，使锁内复查第一子句为真
        svc._backend_process = _FakePopenProc(pid=999)

        with pytest.raises(HTTPException) as ex:
            await start_service(ServiceConfig(**self._CFG))
        assert ex.value.status_code == 400
        assert gbp_calls["n"] == 2  # 锁内复查确实执行
        assert len(popen_calls) == 0  # 拒绝发生在 Popen 之前

    @pytest.mark.asyncio
    async def test_concurrent_start_single_popen(self, monkeypatch, _svc_globals_reset):
        popen_calls = _patch_start_env(monkeypatch, _make_fake_psutil(running=True))
        cfg = ServiceConfig(**self._CFG)

        results, errors = [], []
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait(timeout=5)
            try:
                results.append(asyncio.run(start_service(cfg)))
            except HTTPException as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(results) == 1 and len(errors) == 1
        assert errors[0].status_code == 400
        # 并发下仅允许一次 Popen——证明检查与 Popen 原子（E7 修复前会双实例）
        assert len(popen_calls) == 1


class TestStopFallbackCwdGuard:
    """E8：兜底扫描 cmdline 命中后必须校验 cwd，防误杀其它项目同名模块进程。"""

    _CMDLINE = ["python", "-m", "uvicorn", "server.main:app"]

    def _patch_stop_env(self, monkeypatch, iter_procs):
        fake_psutil = _make_fake_psutil(iter_procs=iter_procs)
        looked_up = []
        real_fake_process = fake_psutil.Process

        def tracking_process(pid):
            looked_up.append(pid)
            return real_fake_process(pid)

        fake_psutil.Process = tracking_process
        monkeypatch.setattr(svc, "psutil", fake_psutil)
        monkeypatch.setattr(svc, "_read_pidfile", lambda: None)
        monkeypatch.setattr(svc, "_remove_pidfile", lambda: None)
        return looked_up

    @pytest.mark.asyncio
    async def test_fallback_terminates_only_project_cwd(self, monkeypatch, _svc_globals_reset):
        project_root = svc.get_project_root()
        foreign_dir = os.path.abspath(os.path.join(project_root, "..", "other_project"))

        foreign = _IterProc(111, self._CMDLINE, cwd=foreign_dir)
        denied = _IterProc(333, self._CMDLINE, cwd_error=psutil.AccessDenied())
        ours = _IterProc(222, self._CMDLINE, cwd=project_root)

        looked_up = self._patch_stop_env(monkeypatch, [foreign, denied, ours])

        out = await stop_service()

        assert out["status"] == "success"
        # 仅 cwd 落在本项目根的进程被定位并 terminate；
        # 外部项目 cwd / 拒绝访问 cwd 的进程均被保守跳过
        # （若 foreign/denied 被命中，looked_up 将是 [111]/[333]）
        assert looked_up == [222]

    @pytest.mark.asyncio
    async def test_fallback_foreign_cwd_only_raises_not_running(self, monkeypatch, _svc_globals_reset):
        project_root = svc.get_project_root()
        foreign_dir = os.path.abspath(os.path.join(project_root, "..", "elsewhere"))
        foreign = _IterProc(111, self._CMDLINE, cwd=foreign_dir)

        self._patch_stop_env(monkeypatch, [foreign])

        with pytest.raises(HTTPException) as ex:
            await stop_service()
        assert ex.value.status_code == 400
        assert "not running" in str(ex.value.detail)


class TestBackendPortRegistration:
    """E16：start 后 _backend_port 记录实际配置端口，/service/status 回读非兜底 8000。"""

    @pytest.mark.asyncio
    async def test_status_reports_configured_port(self, monkeypatch, _svc_globals_reset):
        _patch_start_env(monkeypatch, _make_fake_psutil(running=True))

        cfg = ServiceConfig(host="127.0.0.1", port=8123, use_conda=False)
        out = await start_service(cfg)
        assert out["status"] == "success"
        assert out["port"] == 8123
        # E16 修复点：模块级 _backend_port 被真实更新（修复前恒为 None）
        assert svc._backend_port == 8123

        status = await get_service_status()
        assert status.running is True
        assert status.port == 8123  # 修复前回退兜底 8000
        assert status.pid == 1001


# --------------------------------------------------------------------------- #
# E10 修复回归 —— /service/logs lines 参数边界钳制
# （lines=0 不得经 [-0:] 退化为全量日志 / 负数钳到 1 / 超大值钳到 10000）
# --------------------------------------------------------------------------- #
class TestGetServiceLogsLinesValidation:
    """E10：lines 参数校验——修复前 lines=0 时 all_lines[-0:] 等价 [0:] 返回全量。"""

    _TOTAL = 150

    def _write_log_file(self, tmp_path):
        log_file = tmp_path / "cxo.log"
        log_file.write_text(
            "".join(f"L{i:04d}\n" for i in range(1, self._TOTAL + 1)), encoding="utf-8"
        )
        return str(log_file)

    @pytest.mark.asyncio
    async def test_lines_boundary_clamping(self, monkeypatch, tmp_path, _svc_globals_reset):
        monkeypatch.setattr(svc, "_backend_log_path", self._write_log_file(tmp_path))

        # lines=0：修复后归位默认值 100 行（修复前返回全量 150 行——语义反转）
        out0 = await svc.get_service_logs(lines=0)
        assert out0["status"] == "success"
        assert out0["logs"] == "".join(
            f"L{i:04d}\n" for i in range(self._TOTAL - 99, self._TOTAL + 1)
        )

        # 负数：钳到 1，仅返回末行（修复前 [-(-5):] 跳过首 5 行返回 145 行）
        out_neg = await svc.get_service_logs(lines=-5)
        assert out_neg["logs"] == f"L{self._TOTAL:04d}\n"

        # 超大值：钳到 10000 上界，未超文件实际行数时返回全量
        out_big = await svc.get_service_logs(lines=10**9)
        assert out_big["logs"].count("\n") == self._TOTAL

        # 正常值不受影响：末 5 行
        out5 = await svc.get_service_logs(lines=5)
        assert out5["logs"] == "".join(
            f"L{i:04d}\n" for i in range(self._TOTAL - 4, self._TOTAL + 1)
        )


# --------------------------------------------------------------------------- #
# E9 修复回归 —— start_service Popen 成功但登记未完成时回收孤儿进程
# （全部 mock，不真实启动/终止任何进程）
# --------------------------------------------------------------------------- #
class _ReapSpyProc:
    """E9 用：记录 terminate/kill/wait 调用的伪进程替身。"""

    def __init__(self, pid: int):
        self.pid = pid
        self.terminated = False
        self.killed = False
        self.wait_calls = 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.wait_calls += 1
        return 0


class _RollbackOnExceptionLock:
    """E9 用锁替身：异常穿过临界区时回滚登记，模拟“已 spawn 但登记未成功”。

    现行代码中 Popen 与 ``_backend_process = new_process`` 赋值之间无可注入
    异常点（相邻语句），故以异常路径回滚全局登记来构造该状态，不改产品代码。
    """

    def __init__(self):
        self._lock = threading.RLock()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            svc._backend_process = None  # 模拟登记未成功
        self._lock.release()
        return False


class TestStartOrphanReap:
    """E9：Popen 成功但登记未成功时，except 分支必须回收孤儿进程并清理 pidfile。"""

    @pytest.mark.asyncio
    async def test_reaps_spawned_process_when_registration_incomplete(
        self, monkeypatch, _svc_globals_reset
    ):
        _patch_start_env(monkeypatch, _make_fake_psutil(running=True))
        monkeypatch.setattr(svc, "_backend_process_lock", _RollbackOnExceptionLock())

        spawned = []

        def fake_popen(cmd, **kwargs):
            proc = _ReapSpyProc(pid=4321)
            spawned.append(proc)
            return proc

        monkeypatch.setattr(svc.subprocess, "Popen", fake_popen)

        pidfile_state = {"armed": False}
        removed = []

        def _raise_write(pid):
            # 模拟登记后 pidfile 写入路径抛异常（锁内赋值后的失败路径）
            pidfile_state["armed"] = True
            raise RuntimeError("pidfile write boom")

        def fake_read_pidfile():
            return 4321 if pidfile_state["armed"] else None

        monkeypatch.setattr(svc, "_write_pidfile", _raise_write)
        monkeypatch.setattr(svc, "_read_pidfile", fake_read_pidfile)
        monkeypatch.setattr(svc, "_remove_pidfile", lambda: removed.append(1))

        with pytest.raises(HTTPException) as ex:
            await start_service(
                ServiceConfig(host="127.0.0.1", port=8123, use_conda=False)
            )
        assert ex.value.status_code == 500

        assert len(spawned) == 1
        # E9 修复点：已 spawn 但登记未成功 → 孤儿进程被 terminate 回收
        assert spawned[0].terminated is True
        # wait 立即返回，无需 kill 兜底
        assert spawned[0].killed is False
        assert spawned[0].wait_calls == 1
        # pidfile 内容确为本进程 PID → 被清理
        assert removed == [1]
        # 登记未成功，全局进程句柄不得指向被回收的孤儿
        assert svc._backend_process is not spawned[0]