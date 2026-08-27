"""
服务管理 API 路由
用于从前端启动/停止/重启后端服务
支持使用内置 Conda 环境或系统 Python
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.api.routers.admin import verify_admin_api_key
from server.core.logging_config import get_contextual_logger
from server.core.utils import get_shared_http_client

router = APIRouter()
logger = get_contextual_logger(__name__)

# 全局变量存储后端进程
_backend_process: Optional[subprocess.Popen] = None
# BUG-B07 修复: 保护对 _backend_process / _backend_log_handle / _backend_log_path
# 的并发读写,避免多请求同时启动/停止后端时出现数据竞争
_backend_process_lock = threading.Lock()
# 后端进程日志文件句柄,防止 GC 关闭文件描述符
_backend_log_handle: Optional[Any] = None
# 后端进程日志文件绝对路径,供 /service/logs 端点读取
_backend_log_path: Optional[str] = None
# 后端进程实际监听端口（start_service 时写入，供 /service/status 回读真实端口）
_backend_port: Optional[int] = None


# ---------------------------------------------------------------------------
# BUG-B04 修复: 配置文件路径统一
# 之前: PUT/POST /service/config 写入 config/default.yaml (YAML)
#       但 server.config 实际从 config.json 加载 —— 写入根本不会生效。
# 现在: 统一读写项目根目录下的 config.json, 与 server.config._get_config_path() 一致。
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# B10 修复: pidfile 支持
# 原实现用 psutil.process_iter 遍历所有进程查找 uvicorn，性能差且 cmdline 匹配脆弱。
# 改为 start_service 时写入 pidfile，get_service_status / stop_service 优先读 pidfile。
# psutil.process_iter 保留为回退（pidfile 不存在或进程已死时）。
# ---------------------------------------------------------------------------


def _get_pidfile_path() -> str:
    """获取 pidfile 绝对路径（项目根目录/logs/backend.pid）。"""
    return os.path.join(get_project_root(), "logs", "backend.pid")


def _write_pidfile(pid: int) -> None:
    """将 PID 写入 pidfile。失败时仅 warning，不影响主流程。"""
    try:
        pidfile = _get_pidfile_path()
        os.makedirs(os.path.dirname(pidfile), exist_ok=True)
        with open(pidfile, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except OSError as e:
        logger.warning(f"写入 pidfile 失败: {e}")


def _read_pidfile() -> Optional[int]:
    """从 pidfile 读取 PID。文件不存在或格式无效时返回 None。"""
    try:
        pidfile = _get_pidfile_path()
        if not os.path.exists(pidfile):
            return None
        with open(pidfile, "r", encoding="utf-8") as f:
            pid_str = f.read().strip()
            return int(pid_str) if pid_str else None
    except (OSError, ValueError) as e:
        logger.warning(f"读取 pidfile 失败: {e}")
        return None


def _remove_pidfile() -> None:
    """删除 pidfile。失败时仅 warning。"""
    try:
        pidfile = _get_pidfile_path()
        if os.path.exists(pidfile):
            os.remove(pidfile)
    except OSError as e:
        logger.warning(f"删除 pidfile 失败: {e}")


def _get_service_config_path() -> str:
    """获取项目根目录下的 config.json 绝对路径。

    与 ``server.config.Settings._get_config_path()`` 保持一致,避免
    写文件与读文件路径不一致导致的"修改不生效"问题。
    """
    return os.path.join(get_project_root(), "config.json")


def _load_service_config_file() -> dict:
    """读取 config.json 现有内容,文件不存在则返回空 dict。"""
    config_path = _get_service_config_path()
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"读取 config.json 失败, 将以空配置继续: {e}")
        return {}


def _save_service_config_file(payload: dict) -> None:
    """将配置 dict 写回 config.json。"""
    config_path = _get_service_config_path()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def _apply_config_updates(current_config: dict, incoming: dict) -> dict:
    """将前端传入的 in-memory 配置片段合并进 current_config。

    同时保持与原 YAML 路径相同的字段语义(vector/models/llm_params/system)，
    但实际写入的是 config.json。
    """
    if "vector" in incoming:
        vector_cfg = incoming["vector"]
        current_config.setdefault("memory", {})

        if "backend" in vector_cfg:
            current_config["memory"]["vector_backend"] = vector_cfg["backend"]

        backend = vector_cfg.get("backend", "chroma")
        if backend == "chroma":
            current_config["memory"].setdefault("chroma", {})
            for key in ["db_path", "collection_name", "vector_size"]:
                if key in vector_cfg:
                    current_config["memory"]["chroma"][key] = vector_cfg[key]
        elif backend == "milvus_lite":
            current_config["memory"].setdefault("milvus_lite", {})
            for key in ["db_path", "vector_size"]:
                if key in vector_cfg:
                    current_config["memory"]["milvus_lite"][key] = vector_cfg[key]
        elif backend in ["weaviate", "weaviate_embedded"]:
            # 第五轮 H3：UnifiedConfig.WeaviateConfig 字段为 host/port/embedded，
            # 旧实现写 weaviate_host/weaviate_port（前端读回键），Pydantic 载入时
            # 被静默丢弃 → 保存永不生效。此处做键映射并落 embedded。
            current_config["memory"].setdefault("weaviate", {})
            weaviate_cfg = current_config["memory"]["weaviate"]
            if "weaviate_host" in vector_cfg:
                weaviate_cfg["host"] = vector_cfg["weaviate_host"]
            if "weaviate_port" in vector_cfg:
                weaviate_cfg["port"] = vector_cfg["weaviate_port"]
            if "vector_size" in vector_cfg:
                weaviate_cfg["vector_size"] = vector_cfg["vector_size"]
            weaviate_cfg["embedded"] = backend == "weaviate_embedded"
        elif backend == "qdrant":
            current_config["memory"].setdefault("qdrant", {})
            for key in ["qdrant_host", "qdrant_port", "vector_size"]:
                if key in vector_cfg:
                    current_config["memory"]["qdrant"][key] = vector_cfg[key]

    if "models" in incoming:
        current_config["models"] = incoming["models"]

    if "model_defaults" in incoming:
        current_config["model_defaults"] = incoming["model_defaults"]

    if "llm_params" in incoming:
        current_config["llm_params"] = incoming["llm_params"]

    if "system" in incoming:
        current_config.setdefault("system", {})
        current_config["system"].update(incoming["system"])
    elif any(k in incoming for k in ["host", "port", "log_level", "reload", "use_conda"]):
        current_config.setdefault("system", {})
        for key in ["host", "port", "log_level", "reload", "use_conda"]:
            if key in incoming:
                current_config["system"][key] = incoming[key]

    return current_config


def _open_backend_log_file(root_dir: str) -> tuple:
    """为子进程打开一个日志文件(覆盖写入),用于重定向 stdout/stderr。

    避免使用 ``subprocess.PIPE`` —— 当子进程输出超过 64KB 缓冲区而无人读取时
    会阻塞死锁(BUG-B03)。返回 ``(log_path, file_handle)``。
    调用方有责任持有 ``file_handle`` 直至进程结束。

    BUG-B07 修复: 通过 ``_backend_process_lock`` 保护 ``_backend_log_handle`` /
    ``_backend_log_path`` 的并发写。
    """
    global _backend_log_handle, _backend_log_path
    # 重开句柄前关闭旧的日志句柄，避免日志文件 fd 泄漏
    with _backend_process_lock:
        if _backend_log_handle is not None:
            try:
                _backend_log_handle.close()
            except OSError:
                pass
            _backend_log_handle = None
    log_dir = os.path.join(root_dir, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception as e:
        logger.warning(f"创建日志目录失败: {e}")
        return None, None

    log_path = os.path.join(log_dir, "cxo.log")
    try:
        handle = open(log_path, "wb", buffering=0)
    except Exception as e:
        logger.warning(f"打开日志文件失败 {log_path}: {e}")
        return None, None

    with _backend_process_lock:
        _backend_log_handle = handle
        _backend_log_path = log_path
    return log_path, handle


class ServiceStatus(BaseModel):
    """服务状态"""

    running: bool
    pid: Optional[int] = None
    port: int = 8000
    uptime: Optional[float] = None  # 运行时间（秒）
    using_conda: bool = False  # 是否使用 Conda 环境


class ServiceConfig(BaseModel):
    """服务配置"""

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    reload: bool = False
    use_conda: bool = True  # 是否优先使用 Conda 环境


def get_project_root() -> str:
    """获取项目根目录"""
    # 从 service.py 所在位置向上回溯到项目根目录
    # service.py 在 backend/api/routers/ 下，所以向上3层
    current_file = os.path.abspath(__file__)
    # backend/api/routers/service.py -> 回到项目根目录
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
    return project_root


def get_conda_python_path() -> Optional[str]:
    """获取内置 Conda 环境的 Python 路径"""
    root_dir = get_project_root()

    # 可能的 Conda Python 路径
    possible_paths = [
        os.path.join(root_dir, "Miniconda3", "python.exe"),
        os.path.join(root_dir, "Miniconda3", "envs", "base", "python.exe"),
        os.path.join(root_dir, "Miniconda3", "envs", "cx_o", "python.exe"),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"Found Conda Python: {path}")
            return path

    return None


def get_conda_activate_script() -> Optional[str]:
    """获取 Conda 激活脚本路径"""
    root_dir = get_project_root()

    activate_script = os.path.join(root_dir, "Miniconda3", "Scripts", "activate.bat")
    if os.path.exists(activate_script):
        return activate_script

    return None


def get_backend_process() -> Optional[psutil.Process]:
    """获取后端进程

    BUG-B07 修复: 通过 ``_backend_process_lock`` 保护 ``_backend_process``
    全局变量在并发请求下的安全访问。
    """
    global _backend_process
    with _backend_process_lock:
        proc = _backend_process

    if proc is None:
        return None

    try:
        process = psutil.Process(proc.pid)
        if process.is_running():
            return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    with _backend_process_lock:
        _backend_process = None
    return None


@router.get("/service/status", response_model=ServiceStatus)
async def get_service_status():
    """获取后端服务状态"""
    global _backend_port
    process = get_backend_process()

    if process is None:
        # B10 修复: 优先读 pidfile，避免遍历所有进程
        pid = _read_pidfile()
        if pid is not None:
            try:
                process = psutil.Process(pid)
                if not process.is_running():
                    process = None
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process = None

    if process is None:
        # 回退到 psutil.process_iter（pidfile 不存在或进程已死时）
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                # B10 修复: cmdline 可能为 None，用 `or []` 确保是列表
                cmdline = proc.info.get("cmdline") or []
                if (
                    cmdline
                    and "uvicorn" in " ".join(cmdline)
                    and "server.main:app" in " ".join(cmdline)
                ):
                    # 找到已运行的进程，直接使用其PID
                    process = proc
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    if process and process.is_running():
        try:
            uptime = time.time() - process.create_time()
        except Exception as e:
            logger.warning(f"获取运行时间失败: {e}")
            uptime = None

        # 检查是否使用了 Conda
        using_conda = False
        try:
            cmdline = process.cmdline()
            if any("miniconda" in arg.lower() or "conda" in arg.lower() for arg in cmdline):
                using_conda = True
        except Exception as e:
            logger.warning(f"检查Conda环境失败: {e}")

        return ServiceStatus(
            running=True,
            pid=process.pid,
            port=_backend_port if _backend_port is not None else 8000,
            uptime=uptime,
            using_conda=using_conda,
        )

    return ServiceStatus(running=False, port=_backend_port if _backend_port is not None else 8000)


def validate_service_config(config: ServiceConfig) -> None:
    """验证服务配置，防止命令注入"""
    # 验证 host
    allowed_hosts = ["0.0.0.0", "127.0.0.1", "localhost"]
    if config.host not in allowed_hosts:
        # 验证 IP 地址格式及范围
        # BUG-B-M10 修复: 原正则 ^(\d{1,3}\.){3}\d{1,3}$ 仅校验格式,
        # 不校验 octet 范围(0-255),999.999.999.999 也能通过。
        # 改用 ipaddress.ip_address() 进行严格校验。
        import ipaddress

        try:
            ipaddress.ip_address(config.host)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid host: {config.host}")

    # 验证端口
    if not (1 <= config.port <= 65535):
        raise HTTPException(status_code=400, detail=f"Invalid port: {config.port}")

    # 验证日志级别
    allowed_log_levels = ["debug", "info", "warning", "error", "critical"]
    if config.log_level.lower() not in allowed_log_levels:
        raise HTTPException(status_code=400, detail=f"Invalid log_level: {config.log_level}")


@router.post("/service/start")
async def start_service(config: ServiceConfig, _: bool = Depends(verify_admin_api_key)):
    """启动后端服务

    BUG-B07 修复: 通过 ``_backend_process_lock`` 保护 ``_backend_process`` 赋值,
    避免多请求同时启动/停止后端时出现数据竞争。
    """
    global _backend_process

    # 验证配置
    validate_service_config(config)

    # 检查是否已在运行
    existing_process = get_backend_process()
    if existing_process is not None:
        raise HTTPException(status_code=400, detail="Service is already running")

    # 在创建子进程前再确认一次,避免 TOCTOU 竞争
    with _backend_process_lock:
        if _backend_process is not None and get_backend_process() is not None:
            raise HTTPException(status_code=400, detail="Service is already running")

    try:
        # 获取项目根目录
        root_dir = get_project_root()

        # 检查是否使用 Conda 环境
        conda_python = get_conda_python_path()
        conda_activate = get_conda_activate_script()
        use_conda = config.use_conda and conda_python is not None

        # 为子进程打开一个日志文件,避免 stdout/stderr=PIPE 死锁 (BUG-B03)
        _log_path, _log_handle = _open_backend_log_file(root_dir)
        if _log_handle is not None:
            _stdout_target = _log_handle
            _stderr_target = _log_handle
        else:
            _stdout_target = subprocess.DEVNULL
            _stderr_target = subprocess.DEVNULL

        if use_conda and sys.platform == "win32" and conda_activate:
            # Windows: 使用 activate.bat 激活环境
            # 使用列表形式的命令避免命令注入
            cmd = [
                "cmd",
                "/c",
                f'"{conda_activate}" base && python -m uvicorn server.main:app '
                f"--host {config.host} --port {config.port} --log-level {config.log_level}",
            ]
            if config.reload:
                cmd[-1] += " --reload"

            logger.info("Starting with Conda activate script")

            # 使用 shell=False 执行命令
            new_process = subprocess.Popen(
                cmd,
                cwd=root_dir,
                stdout=_stdout_target,
                stderr=_stderr_target,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

        elif use_conda and conda_python:
            # 直接使用 Conda Python
            cmd = [
                conda_python,
                "-m",
                "uvicorn",
                "server.main:app",
                "--host",
                config.host,
                "--port",
                str(config.port),
                "--log-level",
                config.log_level,
            ]

            if config.reload:
                cmd.append("--reload")

            logger.info(f"Starting with Conda Python: {' '.join(cmd)}")

            new_process = subprocess.Popen(
                cmd,
                cwd=root_dir,
                stdout=_stdout_target,
                stderr=_stderr_target,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

        else:
            # 使用系统 Python
            cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "server.main:app",
                "--host",
                config.host,
                "--port",
                str(config.port),
                "--log-level",
                config.log_level,
            ]

            if config.reload:
                cmd.append("--reload")

            logger.info(f"Starting with system Python: {' '.join(cmd)}")

            new_process = subprocess.Popen(
                cmd,
                cwd=root_dir,
                stdout=_stdout_target,
                stderr=_stderr_target,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

        # BUG-B07 修复: 在锁内完成对全局 _backend_process 的赋值,保证可见性
        with _backend_process_lock:
            _backend_process = new_process
            # 记录实际监听端口，供 /service/status 回读（不再硬编码 8000）
            _backend_port = config.port

        # B10 修复: 写入 pidfile，供后续 status/stop 端点快速定位进程
        _write_pidfile(new_process.pid)

        logger.info(
            f"Backend service started: PID={new_process.pid}, Port={config.port}, Conda={use_conda}"
        )

        return {
            "status": "success",
            "message": "Service started",
            "pid": new_process.pid,
            "port": config.port,
            "using_conda": use_conda,
        }

    except Exception as e:
        logger.error(f"Failed to start service: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="启动服务失败")


@router.post("/service/stop")
async def stop_service(_: bool = Depends(verify_admin_api_key)):
    """停止后端服务

    BUG-B07 修复: 通过 ``_backend_process_lock`` 保护 ``_backend_process`` 写,
    避免多请求同时停止后端时出现数据竞争。
    """
    global _backend_process

    process = get_backend_process()

    if process is None:
        # B10 修复: 优先读 pidfile 查找进程
        pid = _read_pidfile()
        if pid is not None:
            try:
                process = psutil.Process(pid)
                if not process.is_running():
                    process = None
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                process = None

    if process is None:
        # 回退到 psutil.process_iter —— 仅终止精确匹配的 CX-O 后端进程。
        # 严禁裸 "uvicorn" 匹配（会误杀承载本请求的其它 uvicorn 进程）。
        stopped = False
        found_pid = None
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                # B10 修复: cmdline 可能为 None，用 `or []` 确保是列表
                cmdline = proc.info.get("cmdline") or []
                cmdline_str = " ".join(cmdline)
                if cmdline_str and "uvicorn" in cmdline_str and "server.main:app" in cmdline_str:
                    # 命中精确目标：优先以 pidfile 记录的 backend pid 精确 terminate
                    pidfile_pid = _read_pidfile()
                    found_pid = pidfile_pid if (pidfile_pid is not None and pidfile_pid == proc.pid) else proc.pid
                    stopped = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if stopped and found_pid is not None:
            try:
                target = psutil.Process(found_pid)
                if sys.platform == "win32":
                    target.terminate()
                else:
                    target.send_signal(signal.SIGTERM)
                try:
                    target.wait(timeout=5)
                except psutil.TimeoutExpired:
                    target.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            # B10 修复: 清理可能存在的 stale pidfile
            _remove_pidfile()
            return {"status": "success", "message": "Service stopped"}

        raise HTTPException(status_code=400, detail="Service is not running")

    try:
        # 优雅地终止进程
        if sys.platform == "win32":
            process.terminate()
        else:
            process.send_signal(signal.SIGTERM)

        # 等待进程结束
        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            # 强制终止
            process.kill()

        with _backend_process_lock:
            _backend_process = None

        # B10 修复: 停止后删除 pidfile
        _remove_pidfile()

        logger.info("Backend service stopped")

        return {"status": "success", "message": "Service stopped"}

    except Exception as e:
        logger.error(f"Failed to stop service: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="停止服务失败")


@router.post("/service/restart")
async def restart_service(config: ServiceConfig, _: bool = Depends(verify_admin_api_key)):
    """重启后端服务"""
    try:
        # 先停止
        await stop_service()
    except HTTPException:
        # 服务可能未运行，忽略错误
        pass

    # 等待一下确保端口释放
    import asyncio

    await asyncio.sleep(1)

    # 再启动
    return await start_service(config)


@router.get("/service/logs")
async def get_service_logs(lines: int = 100):
    """获取服务日志"""
    try:
        # B10 修复: 原读相对路径 "logs/cxo.log"，与 _open_backend_log_file 写入的
        # {root}/logs/cxo.log 在 CWD≠项目根时会错位。改为优先使用 _backend_log_path，
        # 回退到项目根目录下的绝对路径。
        log_file = _backend_log_path
        if not log_file:
            log_file = os.path.join(get_project_root(), "logs", "cxo.log")
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                return {"status": "success", "logs": "".join(all_lines[-lines:])}

        return {"status": "success", "logs": "No log file available"}

    except Exception as e:
        logger.error(f"Failed to read logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="读取日志失败")


@router.get("/service/config")
async def get_service_config():
    """获取当前服务配置"""
    from server.config import get_settings

    settings = get_settings()
    conda_available = get_conda_python_path() is not None

    config = {
        "host": settings.config.system.host,
        "port": settings.config.system.port,
        "log_level": settings.config.system.log_level,
        "debug": settings.config.system.debug,
        "conda_available": conda_available,
    }

    if hasattr(settings.config, "models"):
        config["models"] = settings.config.models

    if hasattr(settings.config, "model_defaults"):
        config["model_defaults"] = settings.config.model_defaults

    if hasattr(settings.config, "llm_params"):
        config["llm_params"] = settings.config.llm_params

    if hasattr(settings.config, "memory"):
        memory_config = settings.config.memory
        vector_config = {
            "backend": getattr(memory_config, "vector_backend", "chroma"),
            "vector_size": 768,
        }

        backend = vector_config["backend"]
        if backend == "chroma" and hasattr(memory_config, "chroma"):
            chroma_cfg = memory_config.chroma
            vector_config["db_path"] = getattr(chroma_cfg, "db_path", "data/chroma_db")
            vector_config["collection_name"] = getattr(
                chroma_cfg, "collection_name", "memory_vectors"
            )
            vector_config["vector_size"] = getattr(chroma_cfg, "vector_size", 768)
        elif backend == "milvus_lite" and hasattr(memory_config, "milvus_lite"):
            milvus_cfg = memory_config.milvus_lite
            vector_config["db_path"] = getattr(milvus_cfg, "db_path", "data/milvus_lite.db")
            vector_config["vector_size"] = getattr(milvus_cfg, "vector_size", 768)
        elif backend in ["weaviate", "weaviate_embedded"] and hasattr(memory_config, "weaviate"):
            weaviate_cfg = memory_config.weaviate
            vector_config["weaviate_host"] = getattr(weaviate_cfg, "host", "localhost")
            vector_config["weaviate_port"] = getattr(weaviate_cfg, "port", 8080)
            vector_config["vector_size"] = getattr(weaviate_cfg, "vector_size", 768)
        elif backend == "qdrant" and hasattr(memory_config, "qdrant"):
            qdrant_cfg = memory_config.qdrant
            vector_config["qdrant_host"] = getattr(qdrant_cfg, "host", "localhost")
            vector_config["qdrant_port"] = getattr(qdrant_cfg, "port", 6333)
            vector_config["vector_size"] = getattr(qdrant_cfg, "vector_size", 768)

        config["vector"] = vector_config

    return {"status": "success", "config": config}


@router.get("/config/gateway")
async def get_gateway_config():
    """获取单体架构网关配置（简化版，供前端兼容）"""
    monolith_config = {
        "status": "集成",
        "url": "ws://127.0.0.1:8000/ws",
        "http_url": "http://127.0.0.1:8000",
        "timeout": 30,
        "asr": {"status": "集成", "note": "已集成到主服务"},
        "tts": {"status": "集成", "note": "已集成到主服务"},
    }

    return {"status": "success", "config": monolith_config}


@router.put("/service/config")
async def update_service_config_put(config: dict, _: bool = Depends(verify_admin_api_key)):
    """更新服务配置（PUT方法，需要重启生效）

    第五轮 H2：该端点可任意改写 config.json，此前无鉴权；前端未接线，
    挂 verify_admin_api_key 保护（供外部管理 agent 携带密钥调用）。

    BUG-B04 修复: 统一写入项目根目录的 config.json，与 ``server.config``
    加载路径一致；写入后立即 reload Settings，确保运行期内存配置随之更新。
    """
    try:
        current_config = _load_service_config_file()
        _apply_config_updates(current_config, config)
        _save_service_config_file(current_config)

        # 同步热更新 settings 单例，避免前端写入后立即读取仍拿到旧值
        try:
            from server.config import get_settings

            get_settings().reload_config()
        except Exception as e:
            logger.warning(f"reload config 失败, 下次重启生效: {e}")

        # BUG-B-M11 修复: 原函数无 return 语句,FastAPI 返回 null 响应体。
        return {"status": "success"}

    except Exception as e:
        logger.error(f"Failed to save config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="保存配置失败")


@router.post("/service/config")
async def update_service_config(config: dict, _: bool = Depends(verify_admin_api_key)):
    """更新服务配置（需要重启生效）

    BUG-B04 修复: 统一读写 config.json，避免与 server.config 加载路径不一致。
    """
    try:
        current_config = _load_service_config_file()
        _apply_config_updates(current_config, config)
        _save_service_config_file(current_config)

        # 同步热更新 settings 单例
        try:
            from server.config import get_settings

            get_settings().reload_config()
        except Exception as e:
            logger.warning(f"reload config 失败, 下次重启生效: {e}")

        return {"status": "success", "message": "Configuration updated, restart to apply changes"}

    except Exception as e:
        logger.error(f"Failed to save config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="保存配置失败")


@router.get("/service/environment")
async def get_environment_info(_: bool = Depends(verify_admin_api_key)):
    """获取环境信息（含 Python/Conda 路径，第五轮 H2 补鉴权）"""
    conda_python = get_conda_python_path()
    conda_activate = get_conda_activate_script()

    return {
        "status": "success",
        "environment": {
            "conda_available": conda_python is not None,
            "conda_python_path": conda_python,
            "conda_activate_script": conda_activate,
            "system_python": sys.executable,
            "platform": sys.platform,
        },
    }


@router.get("/service/startup-command")
async def get_startup_command(use_conda: bool = True, _: bool = Depends(verify_admin_api_key)):
    """获取启动命令（供前端直接执行；第五轮 H2 补鉴权）"""
    conda_python = get_conda_python_path()
    project_root = get_project_root()

    config = {"host": "0.0.0.0", "port": 8000, "log_level": "info"}

    from server.config import get_settings

    settings = get_settings()
    try:
        config["host"] = settings.config.system.host
        config["port"] = settings.config.system.port
        config["log_level"] = settings.config.system.log_level
    except Exception:
        pass

    startup_info = {
        "status": "success",
        "command": None,
        "args": [],
        "use_conda": use_conda,
        "conda_available": conda_python is not None,
        "project_root": project_root,
    }

    if use_conda and conda_python:
        startup_info["command"] = conda_python
        startup_info["args"] = [
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            config["host"],
            "--port",
            str(config["port"]),
            "--log-level",
            config["log_level"],
        ]
    else:
        startup_info["command"] = sys.executable
        startup_info["args"] = [
            "-m",
            "uvicorn",
            "server.main:app",
            "--host",
            config["host"],
            "--port",
            str(config["port"]),
            "--log-level",
            config["log_level"],
        ]

    return startup_info


@router.get("/service/models")
async def get_available_models():
    """获取可用的模型列表"""
    from server.config import get_settings

    settings = get_settings()
    models = []
    providers = []

    # 从配置获取模型信息
    models_config = settings.config.models

    # main 模型
    providers.append(
        {
            "id": "main",
            "name": models_config.main.model,
            "provider": models_config.main.provider,
            "host": models_config.main.host,
            "enabled": True,
        }
    )

    # summary 模型
    providers.append(
        {
            "id": "summary",
            "name": models_config.summary.model,
            "provider": models_config.summary.provider,
            "host": models_config.summary.host,
            "enabled": True,
        }
    )

    # memory 模型
    providers.append(
        {
            "id": "memory",
            "name": models_config.memory.model,
            "provider": models_config.memory.provider,
            "host": models_config.memory.host,
            "enabled": True,
        }
    )

    # 尝试从 Ollama 获取可用模型列表
    try:
        main_host = models_config.main.host
        response = await get_shared_http_client().get(f"{main_host}/api/tags", timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            for model in data.get("models", []):
                models.append(
                    {
                        "name": model.get("name", ""),
                        "size": model.get("size", 0),
                        "modified_at": model.get("modified_at", ""),
                        "details": model.get("details", {}),
                    }
                )
    except Exception as e:
        logger.warning(f"无法获取 Ollama 模型列表: {e}")

    return {"status": "success", "providers": providers, "ollama_models": models}
