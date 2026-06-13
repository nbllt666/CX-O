"""
So-VITS-SVC 训练服务
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
_SPEAKER_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]")

# 训练 / 预处理子步骤默认超时（秒）
_TRAIN_SUBPROCESS_TIMEOUT = 3600.0  # 1 小时
_TRAIN_STOP_WAIT_TIMEOUT = 10.0


async def _wait_for_subprocess_exit(process: asyncio.subprocess.Process, timeout: float) -> bool:
    """等待子进程退出；超时则先 terminate 再 kill，返回是否主动 kill。"""
    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
        return False
    except asyncio.TimeoutError:
        logger.warning(f"Subprocess (pid={process.pid}) did not exit within {timeout}s; terminating")
        try:
            process.terminate()
        except ProcessLookupError:
            return True
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(f"Subprocess (pid={process.pid}) did not exit after terminate; killing")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        return True


def _sanitize_output_name(name: str) -> str:
    """校验 output_name 仅由字母/数字/下划线/连字符组成，防止目录穿越。"""
    base = os.path.basename(name or "")
    if not base or not _OUTPUT_NAME_PATTERN.match(base):
        raise ValueError(
            f"Invalid output_name: {name!r}. "
            "Only letters, digits, underscore and hyphen are allowed and path separators are forbidden."
        )
    return base


def _sanitize_speaker_name(name: str) -> str:
    """清洗 speaker_name：把不在白名单内的字符替换为下划线。"""
    if not name:
        return "speaker"
    cleaned = _SPEAKER_NAME_PATTERN.sub("_", name)
    cleaned = cleaned.strip("_") or "speaker"
    return cleaned


class SoVITSSVCTrainer:
    def __init__(
        self,
        output_dir: str = "data/models/sovits_svc",
        training_data_dir: str = "data/training/sovits_svc",
        so_vits_svc_dir: str = "",
        python_path: str = "python",
    ):
        self._output_dir = Path(output_dir)
        self._training_data_dir = Path(training_data_dir)
        self._so_vits_svc_dir = Path(so_vits_svc_dir) if so_vits_svc_dir else Path("so-vits-svc-4.1-Stable")
        self._python_path = python_path
        self._process: Optional[asyncio.subprocess.Process] = None
        self._task_id: Optional[str] = None
        self._preprocessed: set[str] = set()
        self._monitor_task: Optional[asyncio.Task] = None

    async def _run_subprocess(self, args: list[str]) -> tuple[int, str, str]:
        logger.info(f"Running subprocess: {' '.join(args)} (cwd={self._so_vits_svc_dir})")
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._so_vits_svc_dir),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=_TRAIN_SUBPROCESS_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Subprocess timeout after {_TRAIN_SUBPROCESS_TIMEOUT}s: {' '.join(args)}"
            )
            await _wait_for_subprocess_exit(process, _TRAIN_STOP_WAIT_TIMEOUT)
            raise RuntimeError(
                f"Subprocess timed out after {_TRAIN_SUBPROCESS_TIMEOUT}s: {' '.join(args)}"
            )
        return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    async def preprocess(self, training_data_dir: str, speaker_name: str = "speaker") -> dict:
        # 清洗 speaker_name，移除所有非白名单字符避免路径穿越
        speaker_name = _sanitize_speaker_name(speaker_name)
        raw_dir = Path(training_data_dir) / "raw" / speaker_name
        raw_dir.mkdir(parents=True, exist_ok=True)

        results = {}

        returncode, stdout, stderr = await self._run_subprocess(
            [self._python_path, "resample.py", "-s", "44100", "-d", str(raw_dir)]
        )
        results["resample"] = {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
        }
        if returncode != 0:
            logger.error(f"Resample failed: {stderr}")
            return results

        returncode, stdout, stderr = await self._run_subprocess(
            [self._python_path, "preprocess_flist_config.py", "-s", speaker_name]
        )
        results["preprocess_flist_config"] = {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
        }
        if returncode != 0:
            logger.error(f"Preprocess flist config failed: {stderr}")
            return results

        returncode, stdout, stderr = await self._run_subprocess(
            [self._python_path, "preprocess_hubert_f0.py", "-s", speaker_name]
        )
        results["preprocess_hubert_f0"] = {
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
        }
        if returncode != 0:
            logger.error(f"Preprocess hubert f0 failed: {stderr}")
            return results

        self._preprocessed.add(speaker_name)
        logger.info(f"Preprocessing completed successfully for speaker: {speaker_name}")
        return results

    async def start_training(
        self,
        epochs: int = 10000,
        batch_size: int = 4,
        learning_rate: float = 1e-4,
        output_name: Optional[str] = None,
        speaker_name: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> str:
        if self._process and self._process.returncode is None:
            raise RuntimeError("训练已在进行，请先停止当前训练")

        target_speaker = _sanitize_speaker_name(speaker_name or "speaker")
        if target_speaker not in self._preprocessed:
            raise RuntimeError("Preprocessing must be completed before training. Call preprocess() first.")

        self._task_id = str(uuid.uuid4())
        self._output_dir.mkdir(parents=True, exist_ok=True)

        if output_name:
            output_name = _sanitize_output_name(output_name)
        else:
            output_name = f"sovits_svc_{self._task_id[:8]}"
        output_path = self._output_dir / output_name
        output_path.mkdir(parents=True, exist_ok=True)

        config_path = self._so_vits_svc_dir / "configs" / "config.json"
        model_name = output_name

        logger.info(f"Starting So-VITS-SVC training: {self._task_id}")
        logger.info(f"  Training data: {self._training_data_dir}")
        logger.info(f"  Output: {output_path}")
        logger.info(f"  Epochs: {epochs}, Batch size: {batch_size}, LR: {learning_rate}")

        args = [
            self._python_path,
            "train.py",
            "-c", str(config_path),
            "-m", model_name,
        ]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._so_vits_svc_dir),
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

    async def _monitor_training(
        self,
        total_epochs: int,
        progress_callback: Optional[Callable] = None,
        proc: Optional[asyncio.subprocess.Process] = None,
    ):
        epoch_pattern = re.compile(r"epoch:\s*(\d+)", re.IGNORECASE)
        current_epoch = 0
        process = proc or self._process
        if process is None:
            logger.warning("Monitor training called without a process")
            return

        def _process_line(line_str: str):
            nonlocal current_epoch
            if not line_str:
                return
            match = epoch_pattern.search(line_str)
            if match:
                current_epoch = int(match.group(1))
                progress = min(current_epoch / total_epochs, 1.0) if total_epochs > 0 else 0.0
                if progress_callback:
                    try:
                        progress_callback(
                            progress=progress,
                            epoch=current_epoch,
                            total_epochs=total_epochs,
                            message=line_str,
                        )
                    except Exception as e:
                        logger.warning(f"Progress callback error: {e}")

        stdout_task = asyncio.create_task(self._read_stream(process.stdout, _process_line))
        stderr_task = asyncio.create_task(self._read_stream(process.stderr, _process_line))
        await asyncio.gather(stdout_task, stderr_task)

        # 等到子进程退出，超时则主动 kill（按子进程句柄所对应的进程）。
        try:
            await asyncio.wait_for(process.wait(), timeout=_TRAIN_SUBPROCESS_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                f"Training monitor wait timeout after {_TRAIN_SUBPROCESS_TIMEOUT}s; killing process"
            )
            await _wait_for_subprocess_exit(process, _TRAIN_STOP_WAIT_TIMEOUT)

        if progress_callback:
            try:
                progress_callback(
                    progress=1.0 if process.returncode == 0 else 0.0,
                    epoch=current_epoch,
                    total_epochs=total_epochs,
                    status="completed" if process.returncode == 0 else "failed",
                )
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    async def stop_training(self):
        if self._process and self._process.returncode is None:
            # 跨平台一致：先 terminate 给一个优雅退出窗口，再 wait，超时再 kill。
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(
                    self._process.wait(), timeout=_TRAIN_STOP_WAIT_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Training process did not exit after terminate; killing (pid={self._process.pid})"
                )
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(
                        self._process.wait(), timeout=_TRAIN_STOP_WAIT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    logger.error(
                        f"Training process still alive after kill (pid={self._process.pid})"
                    )
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except (asyncio.CancelledError, Exception):
                pass
        self._process = None
        self._monitor_task = None
        logger.info("So-VITS-SVC training stopped")

    def list_models(self) -> list[dict]:
        models = []
        if self._output_dir.exists():
            for d in self._output_dir.iterdir():
                if d.is_dir():
                    g_files = list(d.glob("G_*.pth"))
                    d_files = list(d.glob("D_*.pth"))
                    if g_files or d_files:
                        models.append({
                            "name": d.name,
                            "path": str(d),
                            "created": d.stat().st_ctime,
                            "g_model": str(g_files[-1]) if g_files else None,
                            "d_model": str(d_files[-1]) if d_files else None,
                        })
        return models
