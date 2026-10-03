"""
VoxCPM 客户端
通过 CLI 子进程调用 VoxCPM 模型，支持 Voice Design / Controllable Clone / Ultimate Clone 三种模式

自 CX-O-VoiceWorkStation/workstation/services/voxcpm_client.py 迁移
（change-id: split-audio-workstation-cxfc-modelstation）。
目录默认值同步改为 ModelStation 路径（2026-09-05 引擎已迁入 engines/）：
- 参考音频白名单根 = CXO-ModelStation/data/input（_MS_ROOT 锚点）；
- working_dir 默认 engines/VoxCPM-main（config 注入绝对路径；绝对路径与 _CXO_ROOT
  拼接时 pathlib 语义为取绝对路径本身，_CXO_ROOT 仅作空值回退锚点保留）。
引擎 CLI 入口修正（2026-09-25，Task 4.5）：由 `-m voxcpm` 改为 `-m voxcpm.cli`
（引擎源码无 __main__.py，console_script 入口为 voxcpm.cli:main）。
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

from modelstation.config import VoxCPMConfig

logger = logging.getLogger(__name__)

# 项目根（.../CX-O）：本文件位于 CXO-ModelStation/modelstation/services/，
# parents[3] = c:\\CX-O（与原 VWS 布局层级相同，语义平移）
_CXO_ROOT = Path(__file__).resolve().parents[3]
# ModelStation 包根（.../CXO-ModelStation）：参考音频白名单锚点
_MS_ROOT = Path(__file__).resolve().parents[2]

# VoxCPM 子进程默认超时（秒），与 SoVITS 保持数量级
_VOXCPM_SUBPROCESS_TIMEOUT = 300.0
_VOXCPM_STOP_WAIT_TIMEOUT = 10.0

# VoxCPM CLI 模块入口：引擎无 __main__.py，必须走 cli 子模块（console_script 入口等价物）
_VOXCPM_MODULE = "voxcpm.cli"


async def _communicate_with_timeout(process: asyncio.subprocess.Process, timeout: float) -> tuple[bytes, bytes]:
    """对 process.communicate() 做超时包装；超时后先 terminate 再 kill 兜底。"""
    try:
        return await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(f"VoxCPM subprocess timeout after {timeout}s (pid={process.pid}); terminating")
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=_VOXCPM_STOP_WAIT_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(f"VoxCPM subprocess did not exit after terminate, killing (pid={process.pid})")
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=_VOXCPM_STOP_WAIT_TIMEOUT)
            except asyncio.TimeoutError:
                pass
        raise


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
        # 允许作为输入参考音频的根目录，默认仅允许注入配置的 input_dir
        # （打包态=用户数据根下 input；回退包内 data/input），
        # 防止任意本地文件读取。G6: 锚定绝对路径，消除 CWD 依赖。
        self._allowed_audio_root = self._resolve_allowed_audio_root()

    @staticmethod
    def _resolve_allowed_audio_root() -> Path:
        """解析参考音频白名单根：优先注入配置 sovits_svc.input_dir，回退包内 data/input。

        打包态包内锚点指向 <安装根>/resources/backend/data/input，与运行期注入的
        用户数据根 input 目录不一致，会把合法输入误判为越权（同类修复见 security_utils）。
        """
        try:
            from modelstation.config import get_settings

            return Path(get_settings().sovits_svc.input_dir).resolve()
        except Exception:
            return (_MS_ROOT / "data" / "input").resolve()

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
                f"audio path must be located under {self._allowed_audio_root}, got: {resolved}"
            )
        return resolved

    def _build_base_args(self) -> list[str]:
        # 入口修正（change-id: package-modelstation-desktop-installer / Task 4.5）：
        # 上游引擎 engines/VoxCPM-main/src/voxcpm 无 __main__.py，`-m voxcpm` 必然报
        # "No module named voxcpm.__main__"；引擎实际入口为 console_script `voxcpm = voxcpm.cli:main`，
        # 故统一改用 `-m voxcpm.cli`（唯一允许的后端行为改动，最小化）。
        args = [
            sys.executable, "-m", _VOXCPM_MODULE,
            "--model-path", self._model_path,
        ]
        return args

    async def _run_subprocess(self, args: list[str], timeout: float = _VOXCPM_SUBPROCESS_TIMEOUT) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._working_dir,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        try:
            stdout, stderr = await _communicate_with_timeout(process, timeout)
        except asyncio.TimeoutError:
            raise VoxCPMError(
                f"VoxCPM subprocess timed out after {timeout}s",
                returncode=None,
            )
        return process.returncode if process.returncode is not None else 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")

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
        ref_path = self._validate_audio_path(reference_audio)
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
        pa_path = self._validate_audio_path(prompt_audio)
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
        """
        轻量级健康检查：仅验证子进程能否成功启动 Python 解释器及 voxcpm 模块，
        不执行任何模型推理操作，避免加载大模型造成阻塞与性能损耗。

        Returns:
            True 表示 CLI 模块可被成功 import 与启动，False 表示不可用。
        """
        try:
            import sys
            # 使用极快的 --help 参数：仅触发模块 import 与 argparse，毫秒级完成
            args = [
                sys.executable, "-m", _VOXCPM_MODULE, "--help",
            ]
            returncode, _stdout, _stderr = await self._run_subprocess(args, timeout=10.0)
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
