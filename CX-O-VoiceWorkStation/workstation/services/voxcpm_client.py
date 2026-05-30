"""
VoxCPM 客户端
通过 CLI 子进程调用 VoxCPM 模型，支持 Voice Design / Controllable Clone / Ultimate Clone 三种模式
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from workstation.config import VoxCPMConfig

logger = logging.getLogger(__name__)

_CXO_ROOT = Path(__file__).resolve().parents[3]


class VoxCPMError(Exception):
    def __init__(self, message: str, returncode: int | None = None, stderr: str | None = None):
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


class VoxCPMClient:
    def __init__(self, config: VoxCPMConfig | None = None) -> None:
        self._config = config or VoxCPMConfig()
        self._model_path = self._config.model_path
        self._device = self._config.device
        self._enable_denoiser = self._config.enable_denoiser
        self._cfg_value = self._config.cfg_value
        self._inference_timesteps = self._config.inference_timesteps
        self._zipenhancer_model_path = self._config.zipenhancer_model_path
        self._working_dir = str(_CXO_ROOT / self._config.working_dir)
        self._model = None

    def _build_base_args(self) -> list[str]:
        args = [
            sys.executable, "-m", "voxcpm",
            "--model-path", self._model_path,
            "--device", self._device,
            "--cfg-value", str(self._cfg_value),
            "--inference-timesteps", str(self._inference_timesteps),
        ]
        if not self._enable_denoiser:
            args.append("--no-denoiser")
        if self._zipenhancer_model_path:
            args.extend(["--zipenhancer-path", self._zipenhancer_model_path])
        return args

    async def _run_subprocess(self, args: list[str]) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
        )
        stdout, stderr = await process.communicate()
        return process.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")

    async def design(self, text: str, control: str, output_path: str, **kwargs: Any) -> Path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        args = self._build_base_args()
        design_args = [
            "design",
            "--text", text,
            "--control", control,
            "--output", str(output),
        ]
        args.extend(design_args)

        for k, v in kwargs.items():
            if k == "cfg_value":
                args.extend(["--cfg-value", str(v)])
            elif k == "inference_timesteps":
                args.extend(["--inference-timesteps", str(v)])

        logger.info(f"VoxCPM design: text={text!r}, control={control!r}, output={output}")
        returncode, stdout, stderr = await self._run_subprocess(args)

        if returncode != 0:
            error_msg = f"VoxCPM design failed (rc={returncode}): {stderr.strip()}"
            logger.error(error_msg)
            raise VoxCPMError(error_msg, returncode=returncode, stderr=stderr)

        if not output.exists():
            error_msg = f"VoxCPM design completed but output file not found: {output}"
            logger.error(error_msg)
            raise VoxCPMError(error_msg)

        logger.info(f"VoxCPM design output: {output}")
        return output

    async def controllable_clone(self, text: str, control: str, reference_audio: str, output_path: str, **kwargs: Any) -> Path:
        ref_path = Path(reference_audio)
        if not ref_path.exists():
            raise ValueError(f"Reference audio file not found: {reference_audio}")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        args = self._build_base_args()
        clone_args = [
            "clone",
            "--text", text,
            "--control", control,
            "--reference-audio", str(ref_path),
            "--output", str(output),
        ]
        args.extend(clone_args)

        if self._enable_denoiser:
            args.append("--denoise")

        for k, v in kwargs.items():
            if k == "cfg_value":
                args.extend(["--cfg-value", str(v)])
            elif k == "inference_timesteps":
                args.extend(["--inference-timesteps", str(v)])

        logger.info(f"VoxCPM controllable_clone: text={text!r}, control={control!r}, ref={ref_path}, output={output}")
        returncode, stdout, stderr = await self._run_subprocess(args)

        if returncode != 0:
            error_msg = f"VoxCPM controllable_clone failed (rc={returncode}): {stderr.strip()}"
            logger.error(error_msg)
            raise VoxCPMError(error_msg, returncode=returncode, stderr=stderr)

        if not output.exists():
            error_msg = f"VoxCPM controllable_clone completed but output file not found: {output}"
            logger.error(error_msg)
            raise VoxCPMError(error_msg)

        logger.info(f"VoxCPM controllable_clone output: {output}")
        return output

    async def ultimate_clone(self, text: str, prompt_audio: str, prompt_text: str, output_path: str, **kwargs: Any) -> Path:
        pa_path = Path(prompt_audio)
        if not pa_path.exists():
            raise ValueError(f"Prompt audio file not found: {prompt_audio}")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        args = self._build_base_args()
        clone_args = [
            "clone",
            "--text", text,
            "--prompt-audio", str(pa_path),
            "--prompt-text", prompt_text,
            "--output", str(output),
        ]
        args.extend(clone_args)

        if self._enable_denoiser:
            args.append("--denoise")

        for k, v in kwargs.items():
            if k == "cfg_value":
                args.extend(["--cfg-value", str(v)])
            elif k == "inference_timesteps":
                args.extend(["--inference-timesteps", str(v)])

        logger.info(f"VoxCPM ultimate_clone: text={text!r}, prompt_audio={pa_path}, prompt_text={prompt_text!r}, output={output}")
        returncode, stdout, stderr = await self._run_subprocess(args)

        if returncode != 0:
            error_msg = f"VoxCPM ultimate_clone failed (rc={returncode}): {stderr.strip()}"
            logger.error(error_msg)
            raise VoxCPMError(error_msg, returncode=returncode, stderr=stderr)

        if not output.exists():
            error_msg = f"VoxCPM ultimate_clone completed but output file not found: {output}"
            logger.error(error_msg)
            raise VoxCPMError(error_msg)

        logger.info(f"VoxCPM ultimate_clone output: {output}")
        return output

    async def health_check(self) -> bool:
        try:
            args = [
                sys.executable, "-m", "voxcpm",
                "design",
                "--text", "health",
                "--output", str(Path(self._working_dir) / "_health_check_tmp.wav"),
                "--model-path", self._model_path,
                "--device", self._device,
                "--no-denoiser",
            ]
            returncode, stdout, stderr = await self._run_subprocess(args)
            tmp = Path(self._working_dir) / "_health_check_tmp.wav"
            if tmp.exists():
                tmp.unlink()
            return returncode == 0
        except Exception as e:
            logger.error(f"VoxCPM health check failed: {e}")
            return False


_client_instance: VoxCPMClient | None = None


def get_voxcpm_client(config: VoxCPMConfig | None = None) -> VoxCPMClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = VoxCPMClient(config=config)
    return _client_instance
