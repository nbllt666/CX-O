"""
So-VITS-SVC 训练服务
"""
from __future__ import annotations

import logging
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class SoVITSSVCTrainer:
    def __init__(
        self,
        output_dir: str = "data/models/sovits_svc",
        training_data_dir: str = "data/training/sovits_svc",
    ):
        self._output_dir = Path(output_dir)
        self._training_data_dir = Path(training_data_dir)
        self._process: Optional[subprocess.Popen] = None
        self._task_id: Optional[str] = None

    async def start_training(
        self,
        epochs: int = 10000,
        batch_size: int = 4,
        learning_rate: float = 1e-4,
        output_name: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> str:
        self._task_id = str(uuid.uuid4())
        self._output_dir.mkdir(parents=True, exist_ok=True)

        output_name = output_name or f"sovits_svc_{self._task_id[:8]}"
        output_path = self._output_dir / output_name
        output_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Starting So-VITS-SVC training: {self._task_id}")
        logger.info(f"  Training data: {self._training_data_dir}")
        logger.info(f"  Output: {output_path}")
        logger.info(f"  Epochs: {epochs}, Batch size: {batch_size}, LR: {learning_rate}")

        return self._task_id

    async def stop_training(self):
        if self._process:
            self._process.terminate()
            self._process = None
        logger.info("So-VITS-SVC training stopped")

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
