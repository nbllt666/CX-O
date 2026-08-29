"""
歌声合成引擎适配层

将歌谱（dict，经 workstation.music.score.validate_score 规范化）合成为原始歌声 WAV：

- SingingEngine：抽象基类，定义 synthesize(score, voice_bank, output_path) -> Path；
- MockSingingEngine：确定性正弦波歌声合成（标准库 wave/struct/math，无第三方依赖），
  用于开发、测试与 CI——同样输入产出字节级一致的合法 WAV；
- DiffSingerEngine：以子进程方式调用外部 DiffSinger 部署（与 sovits_svc_trainer 相同的
  子进程模式）；未部署（目录/解释器/声库缺失）时抛 SingingEngineError，逐项列出缺失项；
- create_singing_engine(config)：按配置 music.singing_engine（mock / diffsinger）构造引擎。
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from workstation.config import MusicConfig, get_settings
from workstation.music.score import pitch_to_midi

logger = logging.getLogger(__name__)

# Mock 合成参数
_SAMPLE_RATE = 44100
_AMPLITUDE = 0.3  # 振幅（满幅比例），0.3 保证正弦叠加不削波

# DiffSinger 子进程超时（秒），与项目 API 超时约定一致
_DIFFSINGER_SUBPROCESS_TIMEOUT = 300.0


class SingingEngineError(RuntimeError):
    """歌声合成引擎错误（未部署 / 子进程失败 / 未产出文件）"""


class SingingEngine(ABC):
    """歌声合成引擎适配协议：输入歌谱，产出原始歌声 WAV"""

    @abstractmethod
    def synthesize(self, score: dict, voice_bank: str, output_path: "str | Path") -> Path:
        """
        将歌谱合成为原始歌声 WAV。

        Args:
            score: 规范化后的歌谱 dict（见 workstation.music.score）
            voice_bank: 声库标识（Mock 引擎忽略此参数；空串表示使用引擎默认声库）
            output_path: 输出 WAV 路径（父目录不存在时自动创建）

        Returns:
            实际产出的 WAV 文件路径

        Raises:
            SingingEngineError: 引擎未就绪或合成失败
            ValueError: 歌谱内容非法（bpm<=0 / melody 为空 / 非法音高）
        """


def _midi_to_freq(midi: int) -> float:
    """MIDI 音号转频率（Hz）：f = 440 * 2^((n-69)/12)"""
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _validate_score_for_synthesis(score: dict) -> None:
    """合成前轻量校验：bpm>0、melody 非空（完整校验由 validate_score 在上游完成）"""
    if not isinstance(score, dict):
        raise ValueError(f"歌谱必须是 dict，实际为 {type(score).__name__}")
    bpm = score.get("bpm")
    if not isinstance(bpm, (int, float)) or isinstance(bpm, bool) or bpm <= 0:
        raise ValueError(f"歌谱 bpm 非法: {bpm!r}（必须为正数）")
    if not score.get("melody"):
        raise ValueError("歌谱 melody 为空，无法合成")


class MockSingingEngine(SingingEngine):
    """
    确定性正弦波歌声合成引擎。

    每个音符生成对应基频的正弦波：时长 = 节拍数 / BPM × 60 秒，采样率 44100Hz、
    16bit 单声道 PCM。算法无随机数、无系统时间、无外部输入，同样歌谱必产出
    字节级一致的 WAV 文件。
    """

    def __init__(self, sample_rate: int = _SAMPLE_RATE):
        if sample_rate <= 0:
            raise ValueError(f"非法采样率: {sample_rate}")
        self._sample_rate = int(sample_rate)

    @property
    def sample_rate(self) -> int:
        """输出 WAV 采样率"""
        return self._sample_rate

    def synthesize(self, score: dict, voice_bank: str, output_path: "str | Path") -> Path:
        # voice_bank 对 Mock 无意义（无音色概念），仅为遵守适配协议而保留
        _validate_score_for_synthesis(score)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        bpm = float(score["bpm"])
        seconds_per_beat = 60.0 / bpm
        scale = _AMPLITUDE * 32767.0

        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            for note in score["melody"]:
                freq = _midi_to_freq(pitch_to_midi(note["pitch"]))
                step = 2.0 * math.pi * freq / self._sample_rate
                n_frames = int(round(float(note["beats"]) * seconds_per_beat * self._sample_rate))
                if n_frames <= 0:
                    continue
                # 单音符一次性 struct.pack，避免逐样本 pack 的开销；int() 截断保证确定性
                pcm = struct.pack(
                    f"<{n_frames}h",
                    *(int(scale * math.sin(step * i)) for i in range(n_frames)),
                )
                wf.writeframesraw(pcm)

        logger.info(
            "MockSingingEngine 合成完成: %s（%d 音符，bpm=%.3g，sr=%d）",
            out,
            len(score["melody"]),
            bpm,
            self._sample_rate,
        )
        return out


def _is_path_like(ref: str) -> bool:
    """判断 python 解释器配置是路径（而非 PATH 中的命令名）"""
    return (
        os.sep in ref
        or (os.altsep is not None and os.altsep in ref)
        or ref.lower().endswith(".exe")
    )


def _voice_bank_candidates(diffsinger_dir: Path, voice_bank: str) -> list[Path]:
    """声库可能落点：绝对/含分隔符路径按原样检查；裸名称检查 DiffSinger 根目录、
    voicebanks/ 子目录与 checkpoints/ 子目录（DiffSinger 预训练模型惯例位于 checkpoints/<exp>/）"""
    p = Path(voice_bank)
    if p.is_absolute() or _is_path_like(voice_bank):
        return [p]
    return [
        diffsinger_dir / voice_bank,
        diffsinger_dir / "voicebanks" / voice_bank,
        diffsinger_dir / "checkpoints" / voice_bank,
    ]


def check_diffsinger_deployment(
    diffsinger_dir: str, diffsinger_python: str, voice_bank: str
) -> list[str]:
    """
    逐项检查 DiffSinger 部署就绪情况。

    Returns:
        缺失项描述列表（每项含具体路径/名称）；空列表表示全部就绪
    """
    missing: list[str] = []

    dir_str = str(diffsinger_dir or "").strip()
    if not dir_str:
        missing.append("DiffSinger 目录未配置（music.diffsinger_dir 为空）")
        base_dir: Optional[Path] = None
    else:
        base_dir = Path(dir_str)
        if not base_dir.is_dir():
            missing.append(f"DiffSinger 目录不存在: {dir_str}")

    py_str = str(diffsinger_python or "").strip()
    if not py_str:
        missing.append("DiffSinger Python 解释器未配置（music.diffsinger_python 为空）")
    elif _is_path_like(py_str):
        if not Path(py_str).is_file():
            missing.append(f"DiffSinger Python 解释器不存在: {py_str}")
    elif shutil.which(py_str) is None:
        missing.append(f"DiffSinger Python 解释器不在 PATH 中: {py_str}")

    vb_str = str(voice_bank or "").strip()
    if not vb_str:
        missing.append("声库未配置（music.voice_bank 为空）")
    elif base_dir is not None:
        candidates = _voice_bank_candidates(base_dir, vb_str)
        if not any(c.exists() for c in candidates):
            locations = "、".join(str(c) for c in candidates)
            missing.append(f"声库缺失: {vb_str}（已查找: {locations}）")

    return missing


class DiffSingerEngine(SingingEngine):
    """
    DiffSinger 歌声合成引擎：子进程调用外部部署（与 sovits_svc_trainer 同模式）。

    构造时不做部署检查（允许先实例化再择时合成）；synthesize 时逐项检查，
    未部署抛 SingingEngineError 并列出全部缺失项与安装指引。
    """

    def __init__(
        self,
        diffsinger_dir: str,
        diffsinger_python: str = "python",
        voice_bank: str = "",
        subprocess_timeout: float = _DIFFSINGER_SUBPROCESS_TIMEOUT,
    ):
        self._diffsinger_dir = str(diffsinger_dir or "")
        self._diffsinger_python = str(diffsinger_python or "python")
        self._voice_bank = str(voice_bank or "")
        self._subprocess_timeout = subprocess_timeout

    def check_deployment(self, voice_bank: Optional[str] = None) -> list[str]:
        """逐项检查部署，返回缺失项描述列表（空列表 = 就绪）"""
        return check_diffsinger_deployment(
            self._diffsinger_dir,
            self._diffsinger_python,
            self._voice_bank if voice_bank is None else voice_bank,
        )

    def synthesize(self, score: dict, voice_bank: str, output_path: "str | Path") -> Path:
        _validate_score_for_synthesis(score)
        effective_bank = voice_bank or self._voice_bank

        missing = self.check_deployment(effective_bank)
        if missing:
            items = "\n".join(f"  - {item}" for item in missing)
            raise SingingEngineError(
                "DiffSinger 引擎未就绪，缺失项如下：\n"
                f"{items}\n"
                "请先运行安装/检查脚本: python -m workstation.tools.setup_singing_engine"
            )

        base_dir = Path(self._diffsinger_dir)
        bank_path = next(
            (c for c in _voice_bank_candidates(base_dir, effective_bank) if c.exists()),
            None,
        )
        if bank_path is None:
            # 防御 TOCTOU：check_deployment 通过后候选目录被移除时，不再裸抛 StopIteration
            raise SingingEngineError(
                f"未找到可用的声库目录: bank={effective_bank}, base_dir={base_dir}\n"
                "请先运行安装/检查脚本: python -m workstation.tools.setup_singing_engine"
            )
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        score_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="voicews_score_", delete=False, encoding="utf-8"
        )
        try:
            with score_file:
                json.dump(score, score_file, ensure_ascii=False)
            args = [
                self._diffsinger_python,
                "voicews_inference.py",
                "--score",
                score_file.name,
                "--voice_bank",
                str(bank_path),
                "--output",
                str(out),
            ]
            logger.info("调用 DiffSinger 子进程: %s（cwd=%s）", " ".join(args), base_dir)
            try:
                proc = subprocess.run(
                    args,
                    cwd=str(base_dir),
                    capture_output=True,
                    text=True,
                    timeout=self._subprocess_timeout,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32"
                    else 0,
                )
            except subprocess.TimeoutExpired as exc:
                raise SingingEngineError(
                    f"DiffSinger 子进程超时（>{self._subprocess_timeout:.0f}s）: {' '.join(args)}"
                ) from exc
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip()[-500:]
                raise SingingEngineError(
                    f"DiffSinger 子进程失败（退出码 {proc.returncode}）: {tail}"
                )
            if not out.is_file():
                raise SingingEngineError(
                    f"DiffSinger 子进程结束但未产出文件: {out}"
                )
            logger.info("DiffSinger 合成完成: %s", out)
            return out
        finally:
            try:
                os.unlink(score_file.name)
            except OSError:
                pass


def create_singing_engine(config: Optional[MusicConfig] = None) -> SingingEngine:
    """
    按配置构造歌声合成引擎。

    Args:
        config: MusicConfig；为 None 时读取全局 get_settings().music

    Returns:
        MockSingingEngine 或 DiffSingerEngine 实例

    Raises:
        ValueError: music.singing_engine 不是 mock / diffsinger
    """
    cfg = config if config is not None else get_settings().music
    kind = (cfg.singing_engine or "mock").strip().lower()
    if kind == "mock":
        return MockSingingEngine()
    if kind == "diffsinger":
        return DiffSingerEngine(
            diffsinger_dir=cfg.diffsinger_dir,
            diffsinger_python=cfg.diffsinger_python,
            voice_bank=cfg.voice_bank,
        )
    raise ValueError(
        f"未知歌声合成引擎类型: {cfg.singing_engine!r}（支持: mock / diffsinger）"
    )
