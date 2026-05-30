"""
So-VITS-SVC 训练服务
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


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
        self._preprocessed: bool = False

    async def _run_subprocess(self, args: list[str]) -> tuple[int, str, str]:
        logger.info(f"Running subprocess: {' '.join(args)} (cwd={self._so_vits_svc_dir})")
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._so_vits_svc_dir),
        )
        stdout, stderr = await process.communicate()
        return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")

    async def preprocess(self, training_data_dir: str, speaker_name: str = "speaker") -> dict:
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

        self._preprocessed = True
        logger.info("Preprocessing completed successfully")
        return results

    async def start_training(
        self,
        epochs: int = 10000,
        batch_size: int = 4,
        learning_rate: float = 1e-4,
        output_name: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> str:
        if not self._preprocessed:
            raise RuntimeError("Preprocessing must be completed before training. Call preprocess() first.")

        self._task_id = str(uuid.uuid4())
        self._output_dir.mkdir(parents=True, exist_ok=True)

        output_name = output_name or f"sovits_svc_{self._task_id[:8]}"
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

        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._so_vits_svc_dir),
        )

        asyncio.create_task(self._monitor_training(epochs, progress_callback))

        return self._task_id

    async def _monitor_training(self, total_epochs: int, progress_callback: Optional[Callable] = None):
        epoch_pattern = re.compile(r"epoch:\s*(\d+)", re.IGNORECASE)
        current_epoch = 0

        while self._process and self._process.returncode is None:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    line = await self._process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

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

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error monitoring training: {e}")
                break

        if self._process:
            await self._process.wait()

        if progress_callback:
            try:
                progress_callback(
                    progress=1.0 if self._process and self._process.returncode == 0 else 0.0,
                    epoch=current_epoch,
                    total_epochs=total_epochs,
                    status="completed" if self._process and self._process.returncode == 0 else "failed",
                )
            except Exception as e:
                logger.warning(f"Progress callback error: {e}")

    async def stop_training(self):
        if self._process and self._process.returncode is None:
            self._process.kill()
            await self._process.wait()
        self._process = None
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
