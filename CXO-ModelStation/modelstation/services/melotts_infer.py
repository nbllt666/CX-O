"""
MeloTTS 试听推理服务（子进程调用 engines/MeloTTS/melo/infer.py）

与 sovits_svc_infer.SoVITSSVCInferer 同构：模型路径校验根为训练产出目录
（models_dir，附带引擎 logs 目录放行），产物落 audition_dir，经
/api/audio-files/audition 播放。

上游 infer.py 实码约束（engines/MeloTTS/melo/infer.py）：
- CLI：--ckpt_path / --text / --language / --output_dir；
- config.json 固定取 ckpt 同目录（os.path.dirname(ckpt_path)）；
- 产物按说话人写入 `<output_dir>/<spk_name>/output.wav`（目录名不可控），
  故本服务先落临时目录再搬到 audition_dir 根目录并以唯一名命名。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from modelstation.config import get_settings

logger = logging.getLogger(__name__)

_INFER_TIMEOUT_SECONDS = 300.0
_TEXT_MAX_CHARS = 500


class MelottsInferer:
    """MeloTTS 试听推理器（无运行状态，按请求构造即可）。"""

    def __init__(
        self,
        engine_dir: Optional[str] = None,
        models_dir: Optional[str] = None,
        python_path: Optional[str] = None,
        output_dir: Optional[str] = None,
        language: Optional[str] = None,
    ):
        settings = get_settings()
        melotts_cfg = getattr(settings, "melotts", None)
        sovits_cfg = getattr(settings, "sovits_svc", None)
        self._engine_dir = Path(engine_dir or melotts_cfg.engine_dir)
        self._models_dir = Path(models_dir or melotts_cfg.models_dir).resolve()
        self._python_path = python_path or melotts_cfg.python_path
        self._output_dir = Path(output_dir or sovits_cfg.audition_dir)
        self._language = (language or melotts_cfg.language).strip().upper() or "ZH"

    @property
    def infer_script(self) -> Path:
        return self._engine_dir / "melo" / "infer.py"

    # ------------------------------------------------------------------
    # 路径校验
    # ------------------------------------------------------------------
    def _validate_model_path(self, model_path: str) -> Path:
        """model_path 必须是模型目录或 G_*.pth，且位于 models_dir 或引擎 logs 下。"""
        raw = (model_path or "").strip()
        if not raw:
            raise ValueError("model_path is required")
        try:
            resolved = Path(raw).resolve()
        except Exception as e:
            raise ValueError(f"Invalid model_path: {model_path}: {e}")
        allowed_roots = [self._models_dir, (self._engine_dir / "logs").resolve()]
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            raise ValueError(
                f"model_path must be located under one of {allowed_roots}, got: {resolved}"
            )
        return resolved

    def _resolve_checkpoint(
        self, model_path: Path, checkpoint: Optional[str] = None
    ) -> tuple[Path, Path]:
        """定位推理用 ckpt 与 config.json（config 固定为 ckpt 同目录，上游实码）。

        checkpoint 仅在 model_path 为目录时生效：只接受 G_*.pth 文件名（禁止路径分隔符），
        缺省取目录内最新检查点。
        """
        if model_path.is_dir():
            if checkpoint:
                name = str(checkpoint).strip()
                if not name or name != os.path.basename(name):
                    raise ValueError(f"checkpoint 只接受 G_*.pth 文件名: {checkpoint!r}")
                candidate = model_path / name
                if not candidate.is_file():
                    raise FileNotFoundError(f"检查点不存在: {candidate}")
                if not name.startswith("G_") or candidate.suffix.lower() != ".pth":
                    raise ValueError(f"checkpoint 须为 G_*.pth: {name}")
                checkpoint_path = candidate
            else:
                checkpoints = sorted(
                    model_path.glob("G_*.pth"), key=lambda p: p.stat().st_mtime
                )
                if not checkpoints:
                    raise FileNotFoundError(f"模型目录内无 G_*.pth: {model_path}")
                checkpoint_path = checkpoints[-1]
        else:
            if not model_path.is_file():
                raise FileNotFoundError(f"模型文件不存在: {model_path}")
            if model_path.suffix.lower() != ".pth" or not model_path.name.startswith("G_"):
                raise ValueError(f"model_path 须为 G_*.pth 检查点: {model_path.name}")
            checkpoint_path = model_path
        config_path = checkpoint_path.parent / "config.json"
        if not config_path.is_file():
            raise FileNotFoundError(f"检查点同目录缺少 config.json: {config_path}")
        return checkpoint_path, config_path

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    async def infer(
        self,
        model_path: str,
        text: str,
        language: Optional[str] = None,
        checkpoint: Optional[str] = None,
    ) -> tuple[Path, str]:
        """合成试听音频，返回 (产物绝对路径, 使用的检查点文件名)。

        Raises:
            ValueError: 参数非法（空文本/超长/非法模型路径）
            FileNotFoundError: 模型/检查点/config/推理脚本缺失
            RuntimeError: 子进程失败/超时/未产出音频
        """
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("text 不能为空")
        if len(clean_text) > _TEXT_MAX_CHARS:
            raise ValueError(f"text 长度须 ≤ {_TEXT_MAX_CHARS}，当前 {len(clean_text)}")

        validated_model_path = self._validate_model_path(model_path)
        checkpoint_path, _config_path = self._resolve_checkpoint(
            validated_model_path, checkpoint
        )
        if not self.infer_script.is_file():
            raise FileNotFoundError(f"MeloTTS 推理脚本缺失: {self.infer_script}")

        lang = (language or self._language).strip().upper() or self._language

        self._output_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(
            tempfile.mkdtemp(prefix="melotts_infer_", dir=str(self._output_dir))
        )
        try:
            args = [
                self._python_path,
                str(self.infer_script),
                "--ckpt_path", str(checkpoint_path),
                "--text", clean_text,
                "--language", lang,
                "--output_dir", str(tmp_dir),
            ]
            logger.info(
                f"MeloTTS inference: model={checkpoint_path}, language={lang}, "
                f"text_len={len(clean_text)}"
            )
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._engine_dir),
                env={**os.environ, "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD": "1"},
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                ),
            )
            stdout, stderr = await self._communicate(process)
            if process.returncode != 0:
                err = stderr.decode("utf-8", errors="replace")[-2000:]
                logger.error(f"MeloTTS inference failed (exit={process.returncode}): {err}")
                raise RuntimeError(
                    f"MeloTTS 推理失败（exit={process.returncode}）: {err}"
                )

            produced = sorted(tmp_dir.rglob("*.wav"))
            if not produced:
                err = stderr.decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"MeloTTS 推理未产出音频: {err or '<无 stderr>'}")

            output_path = self._output_dir / (
                f"melotts_{checkpoint_path.stem}_{uuid.uuid4().hex[:8]}.wav"
            )
            shutil.move(str(produced[0]), str(output_path))
            logger.info(f"MeloTTS inference completed: {output_path}")
            return output_path, checkpoint_path.name
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    async def _communicate(
        process: asyncio.subprocess.Process,
    ) -> tuple[bytes, bytes]:
        """communicate + 超时 terminate→kill 兜底。"""
        try:
            return await asyncio.wait_for(
                process.communicate(), timeout=_INFER_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(
                f"MeloTTS inference timeout after {_INFER_TIMEOUT_SECONDS}s "
                f"(pid={process.pid}); terminating"
            )
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
            raise
