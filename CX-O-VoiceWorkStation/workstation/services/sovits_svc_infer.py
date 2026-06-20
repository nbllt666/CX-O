"""
So-VITS-SVC 推理服务
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 推理子进程超时（秒）。覆盖 So-VITS-SVC 默认较长的推理时间，但避免挂死。
_INFER_TIMEOUT_SECONDS = 300.0


async def _communicate_with_timeout(process: asyncio.subprocess.Process, timeout: float) -> tuple[bytes, bytes]:
    """对 process.communicate() 做超时包装；超时后先 terminate 再 kill 兜底。"""
    try:
        return await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(
            f"Subprocess timeout after {timeout}s (pid={process.pid}); terminating..."
        )
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(f"Subprocess did not exit after terminate, killing (pid={process.pid})")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        raise


class SoVITSSVCInferer:
    def __init__(
        self,
        model_path: Optional[str] = None,
        output_dir: str = "data/models/sovits_svc",
        so_vits_svc_dir: str = "",
        python_path: str = "python",
        allowed_audio_root: Optional[str] = None,
    ):
        self._model_path = model_path
        self._output_dir = Path(output_dir)
        self._so_vits_svc_dir = Path(so_vits_svc_dir) if so_vits_svc_dir else Path("so-vits-svc-4.1-Stable")
        self._python_path = python_path
        # 允许作为推理输入的根目录。默认仅允许 input 目录。
        self._allowed_audio_root = (
            Path(allowed_audio_root).resolve() if allowed_audio_root else Path("data/input").resolve()
        )

    def _validate_audio_path(self, audio_path: str) -> Path:
        """校验 audio_path 解析后必须位于允许的根目录之内，防止任意文件传入子进程。"""
        audio = Path(audio_path)
        try:
            resolved = audio.resolve()
        except Exception as e:
            raise ValueError(f"Invalid audio path: {audio_path}: {e}")
        try:
            resolved.relative_to(self._allowed_audio_root)
        except ValueError:
            raise ValueError(
                f"audio_path must be located under {self._allowed_audio_root}, got: {resolved}"
            )
        return resolved

    def _validate_model_path(self, model_path: str) -> Path:
        """校验 model_path 解析后必须位于允许的模型根目录之内
        （data/models/sovits_svc 或 so-vits-svc/logs），防止任意本地文件传入子进程。"""
        path = Path(model_path)
        try:
            resolved = path.resolve()
        except Exception as e:
            raise ValueError(f"Invalid model path: {model_path}: {e}")
        allowed_roots = [
            self._output_dir.resolve(),
            (self._so_vits_svc_dir / "logs").resolve(),
        ]
        for root in allowed_roots:
            if resolved.is_relative_to(root):
                return resolved
        raise ValueError(
            f"model_path must be located under one of {allowed_roots}, got: {resolved}"
        )

    async def infer(
        self,
        audio_path: str,
        speaker_id: int = 0,
        transpose: int = 0,
        model_path: Optional[str] = None,
        cluster_model_path: Optional[str] = None,
    ) -> Path:
        audio = self._validate_audio_path(audio_path)
        if not audio.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        effective_model_path = model_path or self._model_path
        if not effective_model_path:
            raise ValueError("Model path must be provided either via constructor or infer() argument")
        validated_model_path = self._validate_model_path(effective_model_path)

        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"converted_{audio.stem}.wav"

        args = [
            self._python_path,
            "inference_main.py",
            "-n", str(validated_model_path),
            "-t", str(transpose),
            "-s", str(speaker_id),
            "-i", str(audio),
            "-o", str(output_path),
        ]

        if cluster_model_path:
            validated_cluster_path = self._validate_model_path(cluster_model_path)
            args.extend(["-c", str(validated_cluster_path)])

        logger.info(f"So-VITS-SVC inference: {audio_path}, speaker={speaker_id}, transpose={transpose}")

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._so_vits_svc_dir),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        stdout, stderr = await _communicate_with_timeout(process, _INFER_TIMEOUT_SECONDS)

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            logger.error(f"Inference failed: {error_msg}")
            raise RuntimeError(f"Inference failed with return code {process.returncode}: {error_msg}")

        if not output_path.exists():
            raise RuntimeError(f"Inference completed but output file not found: {output_path}")

        logger.info(f"Inference completed: {output_path}")
        return output_path
