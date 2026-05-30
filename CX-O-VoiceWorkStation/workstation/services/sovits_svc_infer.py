"""
So-VITS-SVC 推理服务
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SoVITSSVCInferer:
    def __init__(
        self,
        model_path: Optional[str] = None,
        output_dir: str = "data/models/sovits_svc",
        so_vits_svc_dir: str = "",
        python_path: str = "python",
    ):
        self._model_path = model_path
        self._output_dir = Path(output_dir)
        self._so_vits_svc_dir = Path(so_vits_svc_dir) if so_vits_svc_dir else Path("so-vits-svc-4.1-Stable")
        self._python_path = python_path

    async def infer(
        self,
        audio_path: str,
        speaker_id: int = 0,
        transpose: int = 0,
        model_path: Optional[str] = None,
        cluster_model_path: Optional[str] = None,
    ) -> Path:
        audio = Path(audio_path)
        if not audio.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        effective_model_path = model_path or self._model_path
        if not effective_model_path:
            raise ValueError("Model path must be provided either via constructor or infer() argument")

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"converted_{audio.stem}.wav"

        args = [
            self._python_path,
            "inference_main.py",
            "-n", str(effective_model_path),
            "-t", str(transpose),
            "-s", str(speaker_id),
            "-i", str(audio),
            "-o", str(output_path),
        ]

        if cluster_model_path:
            args.extend(["-c", str(cluster_model_path)])

        logger.info(f"So-VITS-SVC inference: {audio_path}, speaker={speaker_id}, transpose={transpose}")

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._so_vits_svc_dir),
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            logger.error(f"Inference failed: {error_msg}")
            raise RuntimeError(f"Inference failed with return code {process.returncode}: {error_msg}")

        if not output_path.exists():
            raise RuntimeError(f"Inference completed but output file not found: {output_path}")

        logger.info(f"Inference completed: {output_path}")
        return output_path
