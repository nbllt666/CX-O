"""
IndexTTS 2 服务管理器
支持按需启动和自动关闭
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
import sys
import threading
from asyncio import Lock
from enum import Enum
from pathlib import Path
from typing import Optional

import httpx

from workstation.services.index_tts_client import (
    EMOTION_TEMPLATES,
    EMOTION_TEXTS,
    EMOTION_INTENSITY_VALUES,
    ALL_EMOTIONS,
    USER_EMOTIONS,
    INDEX_EMOTIONS,
)

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class IndexTTSManager:
    _instance: Optional["IndexTTSManager"] = None
    _lock: Lock = Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8004",
        start_command: str = "",
        working_dir: str = "IndexTTS",
        auto_stop_delay: int = 300,
        startup_timeout: int = 180,
        root_dir: Optional[Path] = None
    ):
        if self._initialized:
            return

        self._base_url = base_url.rstrip("/")
        self._start_command = start_command
        self._working_dir = working_dir
        self._auto_stop_delay = auto_stop_delay
        self._startup_timeout = startup_timeout
        self._root_dir = root_dir or Path.cwd()

        self._status = ServiceStatus.STOPPED
        self._process: Optional[subprocess.Popen] = None
        self._auto_stop_task: Optional[asyncio.Task] = None
        self._last_activity: float = 0
        self._error_message: str = ""

        self._initialized = True
        logger.info(f"IndexTTSManager initialized: url={base_url}, working_dir={working_dir}")

    @property
    def status(self) -> ServiceStatus:
        return self._status

    @property
    def error_message(self) -> str:
        return self._error_message

    async def _check_service_health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/health")
                return response.status_code == 200
        except Exception:
            return False

    def _start_pipe_drainers(self, process: subprocess.Popen) -> None:
        """启动后台线程持续排空子进程的 stdout/stderr 管道。

        子进程启动时若 stdout/stderr 使用 PIPE 但无消费者，管道缓冲写满后子进程将阻塞。
        这里使用守护线程持续 `readline()` 并把内容记录到 logger，确保 PIPE 始终可写。
        """
        def _drain(stream, label: str):
            try:
                for line in iter(stream.readline, b""):
                    try:
                        decoded = line.decode("utf-8", errors="replace").rstrip()
                    except Exception:
                        decoded = repr(line)
                    if decoded:
                        logger.info(f"[IndexTTS {label}] {decoded}")
            except Exception as e:
                logger.debug(f"Pipe drainer for {label} exited: {e}")

        if process.stdout is not None:
            t_out = threading.Thread(
                target=_drain,
                args=(process.stdout, "stdout"),
                name="indextts-stdout-drain",
                daemon=True,
            )
            t_out.start()
        if process.stderr is not None:
            t_err = threading.Thread(
                target=_drain,
                args=(process.stderr, "stderr"),
                name="indextts-stderr-drain",
                daemon=True,
            )
            t_err.start()

    async def _wait_for_ready(self, timeout: int) -> bool:
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < timeout:
            if await self._check_service_health():
                return True
            await asyncio.sleep(2)
        return False

    async def start(self) -> dict:
        async with self._lock:
            if self._status == ServiceStatus.RUNNING:
                return {"status": "success", "message": "Service already running"}

            if self._status == ServiceStatus.STARTING:
                return {"status": "error", "message": "Service is starting"}

            if not self._start_command:
                return {"status": "error", "message": "Start command not configured"}

            self._status = ServiceStatus.STARTING
            self._error_message = ""
            logger.info("Starting IndexTTS service...")

            try:
                working_path = self._root_dir / self._working_dir

                if sys.platform == "win32":
                    python_exe = str(self._root_dir / "Miniconda3" / "python.exe")
                    cmd_parts = shlex.split(self._start_command, posix=False)
                    if cmd_parts and cmd_parts[0] == "python":
                        cmd_parts[0] = python_exe
                    cmd = cmd_parts
                else:
                    cmd = shlex.split(self._start_command, posix=True)

                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(working_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                )

                logger.info(f"Process started with PID: {self._process.pid}")

                # 启动后台 reader 线程持续排空 PIPE，避免子进程因 PIPE 缓冲满而阻塞
                self._start_pipe_drainers(self._process)

                ready = await self._wait_for_ready(self._startup_timeout)

                if ready:
                    self._status = ServiceStatus.RUNNING
                    self._last_activity = asyncio.get_event_loop().time()
                    logger.info("IndexTTS service started successfully")
                    return {"status": "success", "message": "Service started"}
                else:
                    self._status = ServiceStatus.ERROR
                    self._error_message = "Service failed to start within timeout"
                    if self._process:
                        self._process.kill()
                        self._process = None
                    logger.error(self._error_message)
                    return {"status": "error", "message": self._error_message}

            except Exception as e:
                self._status = ServiceStatus.ERROR
                self._error_message = str(e)
                logger.error(f"Failed to start IndexTTS: {e}")
                return {"status": "error", "message": str(e)}

    async def stop(self) -> dict:
        async with self._lock:
            if self._status == ServiceStatus.STOPPED:
                return {"status": "success", "message": "Service already stopped"}

            if self._status == ServiceStatus.STOPPING:
                return {"status": "error", "message": "Service is stopping"}

            self._status = ServiceStatus.STOPPING
            logger.info("Stopping IndexTTS service...")

            if self._auto_stop_task:
                self._auto_stop_task.cancel()
                self._auto_stop_task = None

            try:
                if self._process:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._process.kill()

                    self._process = None

                self._status = ServiceStatus.STOPPED
                logger.info("IndexTTS service stopped")
                return {"status": "success", "message": "Service stopped"}

            except Exception as e:
                self._status = ServiceStatus.ERROR
                self._error_message = str(e)
                logger.error(f"Failed to stop IndexTTS: {e}")
                return {"status": "error", "message": str(e)}

    async def ensure_running(self) -> bool:
        async with self._lock:
            status = self._status

        if status == ServiceStatus.RUNNING:
            if await self._check_service_health():
                async with self._lock:
                    self._last_activity = asyncio.get_event_loop().time()
                return True

        if status == ServiceStatus.STARTING:
            return await self._wait_for_ready(self._startup_timeout)

        result = await self.start()
        return result.get("status") == "success"

    async def reset_auto_stop_timer(self):
        async with self._lock:
            self._last_activity = asyncio.get_event_loop().time()

            if self._auto_stop_task:
                self._auto_stop_task.cancel()

            if self._auto_stop_delay > 0:
                self._auto_stop_task = asyncio.create_task(self._auto_stop_callback())

    async def _auto_stop_callback(self):
        try:
            await asyncio.sleep(self._auto_stop_delay)

            current_time = asyncio.get_event_loop().time()
            if current_time - self._last_activity >= self._auto_stop_delay:
                logger.info("Auto-stopping IndexTTS service due to inactivity")
                await self.stop()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Auto-stop callback error: {e}")

    async def get_status(self) -> dict:
        async with self._lock:
            is_healthy = False
            if self._status == ServiceStatus.RUNNING:
                is_healthy = await self._check_service_health()
                if not is_healthy:
                    self._status = ServiceStatus.ERROR
                    self._error_message = "Service not responding"

            return {
                "status": self._status.value,
                "url": self._base_url,
                "message": self._error_message,
                "healthy": is_healthy,
                "pid": self._process.pid if self._process else None
            }


def get_emotion_templates() -> dict[str, list[tuple[str, float]]]:
    return EMOTION_TEMPLATES


def get_emotion_template(template_name: str) -> list[tuple[str, float]]:
    return EMOTION_TEMPLATES.get(template_name, [])


def get_all_emotions() -> list[str]:
    return ALL_EMOTIONS


def get_user_emotions() -> list[str]:
    return list(USER_EMOTIONS)


def get_index_emotions() -> list[str]:
    return list(INDEX_EMOTIONS)


def get_emotion_intensities() -> list[float]:
    return EMOTION_INTENSITY_VALUES


def get_emotion_text(emotion: str) -> str:
    return EMOTION_TEXTS.get(emotion, EMOTION_TEXTS.get("normal", ""))


_manager_instance: Optional[IndexTTSManager] = None


def get_indextts_manager(
    base_url: str = "http://127.0.0.1:8004",
    start_command: str = "",
    working_dir: str = "IndexTTS",
    auto_stop_delay: int = 300,
    startup_timeout: int = 180,
    root_dir: Optional[Path] = None
) -> IndexTTSManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = IndexTTSManager(
            base_url=base_url,
            start_command=start_command,
            working_dir=working_dir,
            auto_stop_delay=auto_stop_delay,
            startup_timeout=startup_timeout,
            root_dir=root_dir
        )
    return _manager_instance
