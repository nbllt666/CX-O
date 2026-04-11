"""
服务管理 API 路由
用于从前端启动/停止/重启后端服务
支持使用内置 Conda 环境或系统 Python
"""

import os
import signal
import subprocess
import sys
import time
from typing import Optional

import psutil
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.core.logging_config import get_contextual_logger

router = APIRouter()
logger = get_contextual_logger(__name__)

_backend_process: Optional[subprocess.Popen] = None


class ServiceStatus(BaseModel):
    """服务状态"""

    running: bool
    pid: Optional[int] = None
    port: int = 8000
    uptime: Optional[float] = None
    using_conda: bool = False


class ServiceConfig(BaseModel):
    """服务配置"""

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    reload: bool = False
    use_conda: bool = True


def get_project_root() -> str:
    """获取项目根目录"""
    current_file = os.path.abspath(__file__)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
    return project_root


def get_conda_python_path() -> Optional[str]:
    """获取内置 Conda 环境的 Python 路径"""
    root_dir = get_project_root()

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
    """获取后端进程"""
    global _backend_process
    if _backend_process is None:
        return None

    try:
        process = psutil.Process(_backend_process.pid)
        if process.is_running():
            return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    _backend_process = None
    return None


@router.get("/service/status", response_model=ServiceStatus)
async def get_service_status():
    """获取后端服务状态"""
    process = get_backend_process()

    if process is None:
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline", [])
                if (
                    cmdline
                    and "uvicorn" in " ".join(cmdline)
                    and "server.api.app:app" in " ".join(cmdline)
                ):
                    global _backend_process
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

        using_conda = False
        try:
            cmdline = process.cmdline()
            if any("miniconda" in arg.lower() or "conda" in arg.lower() for arg in cmdline):
                using_conda = True
        except Exception as e:
            logger.warning(f"检查Conda环境失败: {e}")

        return ServiceStatus(
            running=True, pid=process.pid, port=8000, uptime=uptime, using_conda=using_conda
        )

    return ServiceStatus(running=False, port=8000)


def validate_service_config(config: ServiceConfig) -> None:
    """验证服务配置，防止命令注入"""
    allowed_hosts = ["0.0.0.0", "127.0.0.1", "localhost"]
    if config.host not in allowed_hosts:
        import re

        if not re.match(r"^(\d{1,3}\.){3}\d{1,3}$", config.host):
            raise HTTPException(status_code=400, detail=f"Invalid host: {config.host}")

    if not (1 <= config.port <= 65535):
        raise HTTPException(status_code=400, detail=f"Invalid port: {config.port}")

    allowed_log_levels = ["debug", "info", "warning", "error", "critical"]
    if config.log_level.lower() not in allowed_log_levels:
        raise HTTPException(status_code=400, detail=f"Invalid log_level: {config.log_level}")


@router.post("/service/start")
async def start_service(config: ServiceConfig):
    """启动后端服务"""
    global _backend_process

    validate_service_config(config)

    existing_process = get_backend_process()
    if existing_process is not None:
        raise HTTPException(status_code=400, detail="Service is already running")

    try:
        root_dir = get_project_root()

        conda_python = get_conda_python_path()
        conda_activate = get_conda_activate_script()
        use_conda = config.use_conda and conda_python is not None

        if use_conda and sys.platform == "win32" and conda_activate:
            cmd = [
                "cmd",
                "/c",
                f'"{conda_activate}" base && python -m uvicorn server.api.app:app '
                f"--host {config.host} --port {config.port} --log-level {config.log_level}",
            ]
            if config.reload:
                cmd[-1] += " --reload"

            logger.info(f"Starting with Conda activate script")

            _backend_process = subprocess.Popen(
                cmd,
                cwd=root_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

        elif use_conda and conda_python:
            cmd = [
                conda_python,
                "-m",
                "uvicorn",
                "server.api.app:app",
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

            _backend_process = subprocess.Popen(
                cmd,
                cwd=root_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

        else:
            cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "server.api.app:app",
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

            _backend_process = subprocess.Popen(
                cmd,
                cwd=root_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )

        logger.info(
            f"Backend service started: PID={_backend_process.pid}, Port={config.port}, Conda={use_conda}"
        )

        return {
            "status": "success",
            "message": "Service started",
            "pid": _backend_process.pid,
            "port": config.port,
            "using_conda": use_conda,
        }

    except Exception as e:
        logger.error(f"Failed to start service: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to start: {str(e)}")


@router.post("/service/stop")
async def stop_service():
    """停止后端服务"""
    global _backend_process

    process = get_backend_process()

    if process is None:
        stopped = False
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline", [])
                if cmdline and "uvicorn" in " ".join(cmdline):
                    proc.terminate()
                    stopped = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if stopped:
            return {"status": "success", "message": "Service stopped"}

        raise HTTPException(status_code=400, detail="Service is not running")

    try:
        if sys.platform == "win32":
            process.terminate()
        else:
            process.send_signal(signal.SIGTERM)

        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            process.kill()

        _backend_process = None

        logger.info("Backend service stopped")

        return {"status": "success", "message": "Service stopped"}

    except Exception as e:
        logger.error(f"Failed to stop service: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to stop: {str(e)}")


@router.post("/service/restart")
async def restart_service(config: ServiceConfig):
    """重启后端服务"""
    try:
        await stop_service()
    except HTTPException:
        pass

    import asyncio

    await asyncio.sleep(1)

    return await start_service(config)


@router.get("/service/logs")
async def get_service_logs(lines: int = 100):
    """获取服务日志"""
    try:
        log_file = "logs/cxhms.log"
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
                return {"status": "success", "logs": "".join(all_lines[-lines:])}

        return {"status": "success", "logs": "No log file available"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read logs: {str(e)}")


@router.get("/service/config")
async def get_service_config():
    """获取当前服务配置"""
    from server.config import settings

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


@router.post("/service/config")
async def update_service_config(config: dict):
    """更新服务配置（需要重启生效）"""
    try:
        import yaml

        config_path = "config/default.yaml"

        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                current_config = yaml.safe_load(f) or {}
        else:
            current_config = {}

        if "vector" in config:
            vector_cfg = config["vector"]
            if "memory" not in current_config:
                current_config["memory"] = {}

            if "backend" in vector_cfg:
                current_config["memory"]["vector_backend"] = vector_cfg["backend"]

            backend = vector_cfg.get("backend", "chroma")
            if backend == "chroma":
                if "chroma" not in current_config["memory"]:
                    current_config["memory"]["chroma"] = {}
                if "db_path" in vector_cfg:
                    current_config["memory"]["chroma"]["db_path"] = vector_cfg["db_path"]
                if "collection_name" in vector_cfg:
                    current_config["memory"]["chroma"]["collection_name"] = vector_cfg[
                        "collection_name"
                    ]
                if "vector_size" in vector_cfg:
                    current_config["memory"]["chroma"]["vector_size"] = vector_cfg["vector_size"]
            elif backend == "milvus_lite":
                if "milvus_lite" not in current_config["memory"]:
                    current_config["memory"]["milvus_lite"] = {}
                if "db_path" in vector_cfg:
                    current_config["memory"]["milvus_lite"]["db_path"] = vector_cfg["db_path"]
                if "vector_size" in vector_cfg:
                    current_config["memory"]["milvus_lite"]["vector_size"] = vector_cfg[
                        "vector_size"
                    ]
            elif backend in ["weaviate", "weaviate_embedded"]:
                if "weaviate" not in current_config["memory"]:
                    current_config["memory"]["weaviate"] = {}
                if "weaviate_host" in vector_cfg:
                    current_config["memory"]["weaviate"]["host"] = vector_cfg["weaviate_host"]
                if "weaviate_port" in vector_cfg:
                    current_config["memory"]["weaviate"]["port"] = vector_cfg["weaviate_port"]
                if "vector_size" in vector_cfg:
                    current_config["memory"]["weaviate"]["vector_size"] = vector_cfg["vector_size"]
            elif backend == "qdrant":
                if "qdrant" not in current_config["memory"]:
                    current_config["memory"]["qdrant"] = {}
                if "qdrant_host" in vector_cfg:
                    current_config["memory"]["qdrant"]["host"] = vector_cfg["qdrant_host"]
                if "qdrant_port" in vector_cfg:
                    current_config["memory"]["qdrant"]["port"] = vector_cfg["qdrant_port"]
                if "vector_size" in vector_cfg:
                    current_config["memory"]["qdrant"]["vector_size"] = vector_cfg["vector_size"]

        if "models" in config:
            current_config["models"] = config["models"]

        if "model_defaults" in config:
            current_config["model_defaults"] = config["model_defaults"]

        if "llm_params" in config:
            current_config["llm_params"] = config["llm_params"]

        if "system" in config:
            if "system" not in current_config:
                current_config["system"] = {}
            current_config["system"].update(config["system"])
        elif any(k in config for k in ["host", "port", "log_level", "reload", "use_conda"]):
            if "system" not in current_config:
                current_config["system"] = {}
            for key in ["host", "port", "log_level", "reload", "use_conda"]:
                if key in config:
                    current_config["system"][key] = config[key]

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(current_config, f, allow_unicode=True, sort_keys=False)

        return {"status": "success", "message": "Configuration updated, restart to apply changes"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save config: {str(e)}")


@router.get("/service/environment")
async def get_environment_info():
    """获取环境信息"""
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
async def get_startup_command(use_conda: bool = True):
    """获取启动命令（供前端直接执行）"""
    conda_python = get_conda_python_path()
    conda_activate = get_conda_activate_script()
    project_root = get_project_root()

    config = {"host": "0.0.0.0", "port": 8000, "log_level": "info"}

    from server.config import settings

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
            "server.api.app:app",
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
            "server.api.app:app",
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
    import httpx

    from server.config import settings

    models = []
    providers = []

    models_config = settings.config.models

    providers.append(
        {
            "id": "main",
            "name": models_config.main.model,
            "provider": models_config.main.provider,
            "host": models_config.main.host,
            "enabled": True,
        }
    )

    providers.append(
        {
            "id": "summary",
            "name": models_config.summary.model,
            "provider": models_config.summary.provider,
            "host": models_config.summary.host,
            "enabled": True,
        }
    )

    providers.append(
        {
            "id": "memory",
            "name": models_config.memory.model,
            "provider": models_config.memory.provider,
            "host": models_config.memory.host,
            "enabled": True,
        }
    )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            main_host = models_config.main.host
            response = await client.get(f"{main_host}/api/tags")
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
