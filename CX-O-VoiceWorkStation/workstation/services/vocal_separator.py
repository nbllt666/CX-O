"""
音频分离服务（change-id: enhance-cover-pitch-analysis-duet Task 1）

双引擎（引擎代码位于 CX-O-VoiceWorkStation/engines/，依赖与 VWS 主环境隔离，
各自以子进程在引擎目录内执行，模式同 ModelStation sovits 推理）：
- demucs（facebookresearch/demucs，htdemucs + --two-stems=vocals 两轨人声分离）：人声/伴奏分离
  CLI 契约（engines/demucs/demucs/separate.py L21-44 / pretrained.py L35）：
  python -m demucs --two-stems=vocals -n <model> -o <outdir> <track>
  产物：<outdir>/<model>/<trackstem>/vocals.wav 与 no_vocals.wav；
  device 缺省即 cuda-if-available（separate.py L44），auto 时不传 -d
- AudioSep（Audio-AGI/AudioSep）：文本查询拆分双人声部
  调用契约（engines/AudioSep/pipeline.py L10/L20，wrapper=tools/audiosep_runner.py）：
  build_audiosep(config/audiosep_base.yaml, <.ckpt>, device) + separate_audio×2；
  输入 32kHz mono 重采样、输出 32kHz int16 wav

守卫：separation.enabled=false 或引擎目录缺失 → SeparationError（含 setup 指引）；
超时（subprocess_timeout_seconds，默认 600s）→ terminate→kill（对齐
ModelStation sovits_svc_infer._communicate_with_timeout 模式）。
产物落 data/separation/<uid>/。
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from workstation.config import SeparationConfig, get_settings

# VWS 根目录（services → workstation → CX-O-VoiceWorkStation）
_BASE_DIR = Path(__file__).resolve().parents[2]

logger = logging.getLogger(__name__)

# 兼容别名（历史代码用 _VWS_ROOT）
_VWS_ROOT = _BASE_DIR

# AudioSep 推理 wrapper（tools/audiosep_runner.py）
_AUDIODEP_RUNNER = _VWS_ROOT / "tools" / "audiosep_runner.py"

# 引擎缺失/未启用时的统一 setup 指引
_SETUP_HINT = (
    "请执行 python tools/setup_separation.py --clone 克隆引擎，"
    "并按 DEPLOY-SEPARATION.md 安装依赖与权重"
)
# demucs 产物文件名（--two-stems=vocals 固定命名）
_DEMUCS_VOCALS_NAME = "vocals.wav"
_DEMUCS_OTHER_NAME = "no_vocals.wav"


class SeparationError(Exception):
    """分离引擎错误（守卫失败/子进程失败/产物缺失/超时）。

    属性：
        engine: 引擎名（demucs / audiosep），便于错误定位与前端提示
    """

    def __init__(self, engine: str, message: str):
        self.engine = engine
        super().__init__(f"[{engine}] {message}")


async def _communicate_with_timeout(
    process: asyncio.subprocess.Process, timeout: float
) -> tuple[bytes, bytes]:
    """对 process.communicate() 做超时包装；超时先 terminate 再 kill 兜底。

    模式对齐 CXO-ModelStation sovits_svc_infer._communicate_with_timeout。
    超时最终抛 asyncio.TimeoutError，由调用方转 SeparationError。
    """
    try:
        return await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(
            f"Separation subprocess timeout after {timeout}s (pid={process.pid}); terminating..."
        )
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(
                f"Separation subprocess did not exit after terminate, killing (pid={process.pid})"
            )
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
        raise


def _stderr_tail(stderr: bytes | None, limit: int = 500) -> str:
    """取 stderr 尾部若干字符用于错误信息（避免日志爆炸）。"""
    text = (stderr or b"").decode("utf-8", errors="replace").strip()
    return text[-limit:] if text else "<无 stderr>"


class VocalSeparator:
    """双引擎分离器：demucs 人声/伴奏 + AudioSep 双人声部拆分。"""

    def __init__(self, config: SeparationConfig | None = None):
        # 允许注入 config（测试友好）；缺省读全局 settings.separation
        self._config = config if config is not None else get_settings().separation

    @property
    def config(self) -> SeparationConfig:
        return self._config

    # ------------------------------------------------------------------
    # 守卫
    # ------------------------------------------------------------------
    def _guard(self, engine_dir: Path, engine_name: str) -> None:
        """enabled/引擎目录守卫；失败抛 SeparationError（含 setup 指引）。"""
        if not self._config.enabled:
            raise SeparationError(
                engine_name, "分离引擎未启用（separation.enabled=false）"
            )
        if not engine_dir.exists():
            raise SeparationError(
                engine_name, f"引擎目录不存在: {engine_dir}；{_SETUP_HINT}"
            )

    @staticmethod
    def _validate_input(audio_path: str | Path) -> Path:
        """输入音频存在性校验，返回绝对路径。"""
        path = Path(audio_path)
        try:
            resolved = path.resolve()
        except Exception as e:
            raise SeparationError("input", f"Invalid audio path: {audio_path}: {e}")
        if not resolved.exists():
            raise SeparationError("input", f"Audio file not found: {resolved}")
        return resolved

    def _new_output_dir(self) -> Path:
        out_dir = Path(self._config.separation_dir) / uuid.uuid4().hex
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    @staticmethod
    def _subprocess_env() -> dict:
        """子进程 env：在继承基础上前置 FFmpeg 共享 DLL 目录（torchaudio 2.11+
        经 torchcodec 解码需要 FFmpeg full-shared DLL；自包含构建位于 tools/ffmpeg/bin，
        见 DEPLOY-SEPARATION.md）。目录不存在时 env 原样返回。"""
        env = dict(os.environ)
        ffbin = _BASE_DIR / "tools" / "ffmpeg" / "bin"
        if ffbin.is_dir():
            env["PATH"] = str(ffbin) + os.pathsep + env.get("PATH", "")
        return env

    @staticmethod
    async def _run_subprocess(
        args: list[str], cwd: Path, engine_name: str, timeout: float
    ) -> tuple[bytes, bytes, int]:
        """创建子进程并等待完成（含超时 terminate→kill 与非0退出转错误）。"""
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd),
                env=VocalSeparator._subprocess_env(),
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
                ),
            )
        except FileNotFoundError as e:
            raise SeparationError(
                engine_name, f"Python 解释器不可用: {args[0]}: {e}"
            )
        try:
            stdout, stderr = await _communicate_with_timeout(process, timeout)
        except asyncio.TimeoutError:
            raise SeparationError(
                engine_name,
                f"分离子进程超时（>{timeout}s），已终止；如为首次运行可能仍在下载权重，"
                f"可调大 separation.subprocess_timeout_seconds 后重试",
            )
        return stdout, stderr, process.returncode or 0

    # ------------------------------------------------------------------
    # demucs：人声/伴奏分离
    # ------------------------------------------------------------------
    async def separate_vocal_accompaniment(
        self, audio_path: str | Path
    ) -> tuple[Path, Path]:
        """demucs 两轨分离人声/伴奏（模型名默认 htdemucs，config 可换）。

        Returns:
            (vocals_path, accompaniment_path)：data/separation/<uid>/ 下的
            vocals.wav 与 accompaniment.wav。

        Raises:
            SeparationError: 守卫失败 / 子进程失败 / 产物缺失 / 超时。
        """
        cfg = self._config
        engine_dir = Path(cfg.demucs_engine_dir)
        self._guard(engine_dir, "demucs")
        audio = self._validate_input(audio_path)

        out_dir = self._new_output_dir()
        demucs_out = out_dir / "demucs"

        # CLI 形态（engines/demucs 实码）：python -m demucs --two-stems=vocals
        #   -n <model> -o <outdir> <track>；device=auto 时省略 -d（引擎默认
        #   cuda-if-available，separate.py L44），显式 cuda/cpu 才传 -d
        args = [
            cfg.demucs_python_path,
            "-m", "demucs",
            "--two-stems=vocals",
            "-n", cfg.demucs_model,
            "-o", str(demucs_out),
            str(audio),
        ]
        if cfg.device in ("cuda", "cpu"):
            args.extend(["-d", cfg.device])

        logger.info(f"demucs separation start: {audio.name} -> {out_dir}")
        _stdout, stderr, returncode = await self._run_subprocess(
            args, cwd=engine_dir, engine_name="demucs",
            timeout=cfg.subprocess_timeout_seconds,
        )
        if returncode != 0:
            raise SeparationError(
                "demucs",
                f"分离子进程失败（exit={returncode}）: {_stderr_tail(stderr)}",
            )

        vocals_raw = self._find_demucs_output(demucs_out, _DEMUCS_VOCALS_NAME)
        other_raw = self._find_demucs_output(demucs_out, _DEMUCS_OTHER_NAME)

        vocals_path = out_dir / "vocals.wav"
        accompaniment_path = out_dir / "accompaniment.wav"
        shutil.move(str(vocals_raw), str(vocals_path))
        shutil.move(str(other_raw), str(accompaniment_path))
        shutil.rmtree(demucs_out, ignore_errors=True)
        logger.info(f"demucs separation done: {vocals_path} + {accompaniment_path}")
        return vocals_path, accompaniment_path

    @staticmethod
    def _find_demucs_output(demucs_out: Path, filename: str) -> Path:
        """在 demucs 输出目录中定位产物（<outdir>/<model>/<trackstem>/<filename>）。

        产物命名以实码 --filename 默认模板 {track}/{stem}.{ext} 为准；
        单轨输入取 mtime 最新命中，缺失时抛 SeparationError。
        """
        matches = sorted(demucs_out.rglob(filename), key=lambda p: p.stat().st_mtime)
        if not matches:
            raise SeparationError(
                "demucs",
                f"分离完成但产物缺失（{filename}），demucs 输出目录: {demucs_out}",
            )
        return matches[-1]

    # ------------------------------------------------------------------
    # AudioSep：文本查询拆分双人声部
    # ------------------------------------------------------------------
    def _resolve_audiosep_checkpoint(self) -> Path:
        """解析 AudioSep checkpoint：配置显式路径优先；空则扫描引擎 checkpoint/ 目录。"""
        cfg = self._config
        if cfg.audiosep_checkpoint:
            ckpt = Path(cfg.audiosep_checkpoint)
            if not ckpt.exists():
                raise SeparationError(
                    "audiosep",
                    f"配置的 audiosep_checkpoint 不存在: {ckpt}；"
                    f"请按 DEPLOY-SEPARATION.md 下载权重",
                )
            return ckpt
        default_dir = Path(cfg.audiosep_engine_dir) / "checkpoint"
        candidates = sorted(
            default_dir.glob("*.ckpt"), key=lambda p: p.stat().st_mtime
        ) if default_dir.exists() else []
        if not candidates:
            raise SeparationError(
                "audiosep",
                f"未配置 audiosep_checkpoint 且引擎 checkpoint/ 目录无 .ckpt: {default_dir}；"
                f"请按 DEPLOY-SEPARATION.md 下载 audiosep_base_4M_steps.ckpt 与 "
                f"CLAP 权重 music_speech_audioset_epoch_15_esc_89.98.pt",
            )
        return candidates[-1]

    async def split_duet_vocals(
        self,
        vocals_path: str | Path,
        query_a: str = "the lead vocal",
        query_b: str = "the second vocal singing a different melody",
    ) -> tuple[Path, Path]:
        """AudioSep 文本查询拆分双人声部（wrapper 子进程，调用契约见 pipeline.py L10/L20）。

        Args:
            vocals_path: 输入人声 wav（通常为 separate_vocal_accompaniment 的 vocals 产物）
            query_a: A 声部文本查询（默认 lead vocal）
            query_b: B 声部文本查询（默认 second vocal singing a different melody）

        Returns:
            (part_a_path, part_b_path)：data/separation/<uid>/ 下的 part_a.wav 与
            part_b.wav（32kHz mono，由下游消费方按需重采样）。

        Raises:
            SeparationError: 守卫失败 / checkpoint 缺失 / 子进程失败 / 产物缺失 / 超时。
        """
        cfg = self._config
        engine_dir = Path(cfg.audiosep_engine_dir)
        self._guard(engine_dir, "audiosep")
        if not _AUDIODEP_RUNNER.exists():
            raise SeparationError(
                "audiosep", f"推理 wrapper 缺失: {_AUDIODEP_RUNNER}"
            )
        audio = self._validate_input(vocals_path)
        checkpoint = self._resolve_audiosep_checkpoint()

        out_dir = self._new_output_dir()
        part_a_path = out_dir / "part_a.wav"
        part_b_path = out_dir / "part_b.wav"

        args = [
            cfg.audiosep_python_path,
            str(_AUDIODEP_RUNNER),
            "--engine-dir", str(engine_dir),
            "--checkpoint", str(checkpoint),
            "--input", str(audio),
            "--query-a", query_a,
            "--query-b", query_b,
            "--output-a", str(part_a_path),
            "--output-b", str(part_b_path),
            "--device", cfg.device,
        ]

        logger.info(
            f"AudioSep duet split start: {audio.name} (queries: {query_a!r} / {query_b!r})"
        )
        _stdout, stderr, returncode = await self._run_subprocess(
            args, cwd=engine_dir, engine_name="audiosep",
            timeout=cfg.subprocess_timeout_seconds,
        )
        if returncode != 0:
            raise SeparationError(
                "audiosep",
                f"分离子进程失败（exit={returncode}）: {_stderr_tail(stderr)}",
            )

        for label, path in (("part_a.wav", part_a_path), ("part_b.wav", part_b_path)):
            if not path.exists():
                raise SeparationError(
                    "audiosep",
                    f"分离完成但产物缺失（{label}），输出目录: {out_dir}",
                )
        logger.info(f"AudioSep duet split done: {part_a_path} + {part_b_path}")
        return part_a_path, part_b_path
