"""
F5-TTS 微调服务
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _sanitize_output_name(name: str) -> str:
    """校验 output_name 仅由字母/数字/下划线/连字符组成，防止目录穿越。"""
    base = os.path.basename(name or "")
    if not base or not _OUTPUT_NAME_PATTERN.match(base):
        raise ValueError(
            f"Invalid output_name: {name!r}. "
            "Only letters, digits, underscore and hyphen are allowed and path separators are forbidden."
        )
    return base


class F5TTSFinetuneService:
    def __init__(
        self,
        base_model: str = "F5TTS_v1_Base",
        output_dir: str = "data/models/f5tts",
        training_data_dir: str = "data/training/f5tts",
    ):
        self._base_model = base_model
        self._output_dir = Path(output_dir)
        self._training_data_dir = Path(training_data_dir)
        self._process: Optional[asyncio.subprocess.Process] = None
        self._task_id: Optional[str] = None
        self._monitor_task: Optional[asyncio.Task] = None

    async def start_training(
        self,
        epochs: int = 100,
        batch_size: int = 4,
        learning_rate: float = 1e-4,
        output_name: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> str:
        if self._process and self._process.returncode is None:
            raise RuntimeError("训练已在进行，请先停止当前训练")

        self._task_id = str(uuid.uuid4())
        self._output_dir.mkdir(parents=True, exist_ok=True)

        if output_name:
            output_name = _sanitize_output_name(output_name)
        else:
            output_name = f"f5tts_finetuned_{self._task_id[:8]}"
        output_path = self._output_dir / output_name
        output_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting F5-TTS fine-tuning: {self._task_id}")
        logger.info(f"  Base model: {self._base_model}")
        logger.info(f"  Training data: {self._training_data_dir}")
        logger.info(f"  Output: {output_path}")
        logger.info(f"  Epochs: {epochs}, Batch size: {batch_size}, LR: {learning_rate}")

        args = [
            "python", "-m", "f5_tts.train",
            "--model", self._base_model,
            "--data_dir", str(self._training_data_dir),
            "--output_dir", str(output_path),
            "--epochs", str(epochs),
            "--batch_size", str(batch_size),
            "--learning_rate", str(learning_rate),
        ]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        self._process = proc

        self._monitor_task = asyncio.create_task(self._monitor_training(epochs, progress_callback, proc))

        return self._task_id

    async def _read_stream(self, stream, callback):
        while True:
            line = await stream.readline()
            if not line:
                break
            callback(line.decode("utf-8", errors="replace").strip())

    def _log_stdout(self, line: str):
        if line:
            logger.info(f"[F5-TTS train stdout] {line}")

    def _log_stderr(self, line: str):
        if line:
            logger.info(f"[F5-TTS train stderr] {line}")

    async def _monitor_training(
        self,
        total_epochs: int,
        progress_callback: Optional[Callable] = None,
        proc: Optional[asyncio.subprocess.Process] = None,
    ):
        process = proc or self._process
        if process is None:
            logger.warning("Monitor training called without a process")
            return
        stdout_task = asyncio.create_task(self._read_stream(process.stdout, self._log_stdout))
        stderr_task = asyncio.create_task(self._read_stream(process.stderr, self._log_stderr))
        await asyncio.gather(stdout_task, stderr_task)

        await process.wait()

        if progress_callback:
            try:
                progress_callback(
                    progress=1.0 if process.returncode == 0 else 0.0,
                    status="completed" if process.returncode == 0 else "failed",
                )
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

        logger.info(f"F5-TTS training finished with return code: {process.returncode}")

    async def stop_training(self):
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except (asyncio.CancelledError, Exception):
                pass
        self._process = None
        self._monitor_task = None
        logger.info("F5-TTS training stopped")

    def list_models(self) -> list[dict]:
        models = []
        if self._output_dir.exists():
            for d in self._output_dir.iterdir():
                if d.is_dir():
                    models.append({
                        "name": d.name,
                        "path": str(d),
                        "created": d.stat().st_ctime,
                    })
        return models
