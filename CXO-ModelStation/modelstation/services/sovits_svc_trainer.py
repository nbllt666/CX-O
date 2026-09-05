"""
So-VITS-SVC 训练服务

自 CX-O-VoiceWorkStation/workstation/services/sovits_svc_trainer.py 迁移
（change-id: split-audio-workstation-cxfc-modelstation），
import 路径 workstation.* → modelstation.* 全量改写，逻辑不变。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Optional

from modelstation.services.security_utils import validate_training_data_dir

logger = logging.getLogger(__name__)

_OUTPUT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_SPEAKER_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]")

# 训练 / 预处理子步骤默认超时（秒）
_TRAIN_SUBPROCESS_TIMEOUT = 3600.0  # 1 小时
# 训练监控超时（秒）：So-VITS-SVC 训练通常耗时数小时甚至数天，需远大于预处理超时
_TRAIN_MONITOR_TIMEOUT = 7 * 24 * 3600.0  # 7 days for training monitor
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

    @property
    def training_data_dir(self) -> Path:
        """训练数据目录（公开访问接口）。"""
        return self._training_data_dir

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
        # 校验 training_data_dir 必须位于允许的根目录之下，防止目录穿越
        training_data_dir = validate_training_data_dir(training_data_dir)

        results = {}

        # 按上游 argparse 实码重写三步预处理参数：
        #   resample.py:               --sr2 <int> --in_dir <含 speaker 子目录的 raw 根> [--out_dir2]
        #   preprocess_flist_config.py: --train_list/--val_list/--source_dir（默认 ./filelists/*.txt、./dataset/44k）
        #   preprocess_hubert_f0.py:   -d/--device --in_dir --f0_predictor --num_processes
        # 三步 CWD 均为上游仓库根（_run_subprocess 固定 cwd），默认相对路径与上游标准
        # 工作流一致，故仅显式传必要参数。hubert 步骤读 configs/config.json
        # （flist 步骤产出，顺序已保证），--f0_predictor 显式取 pm 与推理默认对齐且免下载
        # rmvpe 模型。
        raw_root = training_data_dir / "raw"
        raw_dir = raw_root / speaker_name
        raw_dir.mkdir(parents=True, exist_ok=True)

        returncode, stdout, stderr = await self._run_subprocess(
            [self._python_path, "resample.py", "--sr2", "44100", "--in_dir", str(raw_root)]
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
            [self._python_path, "preprocess_flist_config.py"]
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
            [self._python_path, "preprocess_hubert_f0.py", "--f0_predictor", "pm"]
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

    @staticmethod
    def _write_runtime_config(
        source_config_path: Path,
        target_path: Path,
        *,
        epochs: int,
        batch_size: int,
        learning_rate: float,
    ) -> None:
        """读取上游 config.json，改写 train 段超参后写入 target_path。

        字段名以上游 configs_template/config_template.json 与 utils.get_hparams 实码为准：
        train.epochs / train.batch_size / train.learning_rate。
        """
        if not source_config_path.exists():
            raise RuntimeError(
                f"上游 config.json 不存在: {source_config_path}（请先完成 preprocess 再训练）"
            )
        with open(source_config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        train_section = config.get("train") if isinstance(config, dict) else None
        if not isinstance(train_section, dict):
            raise RuntimeError(f"上游 config.json 缺少 train 段: {source_config_path}")
        train_section["epochs"] = int(epochs)
        train_section["batch_size"] = int(batch_size)
        train_section["learning_rate"] = float(learning_rate)
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

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

        source_config_path = self._so_vits_svc_dir / "configs" / "config.json"
        model_name = output_name

        # 上游 train.py 仅通过 -c 接收超参（utils.get_hparams），请求中的
        # epochs/batch_size/learning_rate 按请求参数改写上游 config.json 的 train 段
        # 并落盘独立副本到本训练 output_path 下（多训练互不覆盖）。
        runtime_config_path = output_path / "config.json"
        self._write_runtime_config(
            source_config_path,
            runtime_config_path,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
        )

        logger.info(f"Starting So-VITS-SVC training: {self._task_id}")
        logger.info(f"  Training data: {self._training_data_dir}")
        logger.info(f"  Output: {output_path}")
        logger.info(f"  Epochs: {epochs}, Batch size: {batch_size}, LR: {learning_rate}")
        logger.info(f"  Runtime config: {runtime_config_path}")

        args = [
            self._python_path,
            "train.py",
            "-c", str(runtime_config_path),
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
            await asyncio.wait_for(process.wait(), timeout=_TRAIN_MONITOR_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                f"Training monitor wait timeout after {_TRAIN_MONITOR_TIMEOUT}s; killing process"
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
            # join 已取消的监控任务：asyncio.wait 不透传被等待任务自身的
            # CancelledError，任务取消后此处正常返回，后续清理必达。
            done, _ = await asyncio.wait([self._monitor_task])
            for task in done:
                if task.cancelled():
                    continue
                exc = task.exception()
                if exc:
                    logger.debug(f"训练监控任务异常退出: {exc}")
        self._process = None
        self._monitor_task = None
        logger.info("So-VITS-SVC training stopped")

    def list_models(self) -> list[dict]:
        models = []
        if self._output_dir.exists():
            for d in self._output_dir.iterdir():
                if d.is_dir():
                    g_files = sorted(d.glob("G_*.pth"), key=lambda p: p.stat().st_mtime)
                    d_files = sorted(d.glob("D_*.pth"), key=lambda p: p.stat().st_mtime)
                    if g_files or d_files:
                        models.append({
                            "name": d.name,
                            "path": str(d),
                            "created": d.stat().st_mtime,
                            "g_model": str(g_files[-1]) if g_files else None,
                            "d_model": str(d_files[-1]) if d_files else None,
                        })
        models.sort(key=lambda m: m["created"], reverse=True)
        return models
