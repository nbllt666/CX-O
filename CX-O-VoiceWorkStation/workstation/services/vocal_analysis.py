"""
源音频人声音域分析（change-id: enhance-cover-pitch-analysis-duet Task 1）

分析链（spec 对齐）：
- 输入音频（含伴奏时可先经 VocalSeparator 分离人声，见 analyze_with_separation）
- librosa.pyin 提取 F0 序列（离线无模型下载；fmin=65Hz≈C2，fmax=1100Hz≈C#6）
- 置信度阈值（voiced_prob >= f0_confidence）过滤后统计 VoiceProfile：
  f0_median_hz / f0_median_midi / range_low_midi(P10) / range_high_midi(P90) /
  range_span_semitones / voiced_ratio

纯函数核心 compute_profile 不触碰 IO，可直接单测；
无声帧过多（voiced_ratio 过低）抛 VoiceAnalysisError（明确错误，不静默返回）。
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# pyin 搜索范围（Hz）：65 Hz ≈ C2，1100 Hz ≈ C#6，覆盖人声全域
_FMIN_HZ = 65.0
_FMAX_HZ = 1100.0
# 分析重采样率（pyin 对高采样率输入计算量大；22.05k Nyquist 远大于 fmax）
_ANALYSIS_SR = 22050
# 无声判定：有效帧占比低于该值视为无声/噪声主导输入，拒绝分析
_MIN_VOICED_RATIO = 0.05


class VoiceAnalysisError(Exception):
    """音域分析失败（输入无声、文件不可读、空音频等）。"""


@dataclass
class VoiceProfile:
    """人声音域画像（MIDI 音高号：A4=440Hz=69，半音为 1）。"""

    f0_median_hz: float
    f0_median_midi: float
    range_low_midi: float
    range_high_midi: float
    range_span_semitones: float
    voiced_ratio: float

    def to_dict(self) -> dict:
        return asdict(self)


def hz_to_midi(hz: float) -> float:
    """Hz → MIDI 音高号（69 + 12*log2(hz/440)）。纯函数。

    Raises:
        ValueError: hz 非正数。
    """
    if hz <= 0:
        raise ValueError(f"Frequency must be positive, got {hz}")
    return 69.0 + 12.0 * float(np.log2(hz / 440.0))


def compute_profile(
    f0: np.ndarray,
    voiced_prob: np.ndarray,
    f0_confidence: float = 0.6,
) -> VoiceProfile:
    """由 pyin 输出统计 VoiceProfile。纯函数核心（可单测）。

    Args:
        f0: pyin 的 F0 序列（Hz，无声帧为 nan）
        voiced_prob: pyin 的逐帧发声概率序列（0~1）
        f0_confidence: 置信度阈值，voiced_prob 低于该值的帧不计入统计

    Raises:
        VoiceAnalysisError: 空序列 / 有效帧占比过低 / 过滤后无有效 F0。
    """
    f0 = np.asarray(f0, dtype=float)
    voiced_prob = np.asarray(voiced_prob, dtype=float)
    total_frames = int(f0.shape[0])
    if total_frames == 0:
        raise VoiceAnalysisError("No frames to analyze: input audio is empty")

    mask = np.isfinite(f0) & (f0 > 0) & (voiced_prob >= f0_confidence)
    voiced_ratio = float(np.count_nonzero(mask)) / float(total_frames)
    if voiced_ratio < _MIN_VOICED_RATIO:
        raise VoiceAnalysisError(
            f"Input has too few voiced frames (voiced_ratio={voiced_ratio:.4f} < "
            f"{_MIN_VOICED_RATIO} at confidence {f0_confidence}); cannot analyze pitch"
        )

    valid_f0 = f0[mask]
    midi_values = 69.0 + 12.0 * np.log2(valid_f0 / 440.0)
    f0_median = float(np.median(valid_f0))
    midi_median = float(np.median(midi_values))
    range_low = float(np.percentile(midi_values, 10))
    range_high = float(np.percentile(midi_values, 90))
    return VoiceProfile(
        f0_median_hz=f0_median,
        f0_median_midi=midi_median,
        range_low_midi=range_low,
        range_high_midi=range_high,
        range_span_semitones=range_high - range_low,
        voiced_ratio=voiced_ratio,
    )


def analyze_pitch(audio_path: str | Path, f0_confidence: float = 0.6) -> VoiceProfile:
    """分析音频文件的人声音域。

    Args:
        audio_path: 音频文件路径（wav/mp3/flac 等 librosa/soundfile 可解码格式）
        f0_confidence: pyin 置信度阈值（config cover_analysis.f0_confidence 默认）

    Returns:
        VoiceProfile

    Raises:
        VoiceAnalysisError: 文件不存在 / 解码失败 / 空音频 / 无声帧过多。
    """
    import librosa  # 延迟导入：模块导入零重量，用到才拉起 librosa

    path = Path(audio_path)
    if not path.exists():
        raise VoiceAnalysisError(f"Audio file not found: {audio_path}")
    try:
        y, sr = librosa.load(str(path), sr=_ANALYSIS_SR, mono=True)
    except Exception as e:  # noqa: BLE001 - 解码失败统一转分析错误
        raise VoiceAnalysisError(f"Failed to load audio {audio_path}: {e}") from e
    if y.size == 0:
        raise VoiceAnalysisError(f"Audio file is empty: {audio_path}")

    f0, _voiced_flag, voiced_prob = librosa.pyin(
        y, fmin=_FMIN_HZ, fmax=_FMAX_HZ, sr=sr
    )
    if f0 is None or voiced_prob is None:
        raise VoiceAnalysisError(f"pyin returned no pitch data for {audio_path}")
    profile = compute_profile(f0, voiced_prob, f0_confidence)
    logger.info(
        "Voice profile analyzed: %s (median=%.1fHz/%.2fMIDI, range=%.2f~%.2fMIDI, voiced=%.2f%%)",
        path.name,
        profile.f0_median_hz,
        profile.f0_median_midi,
        profile.range_low_midi,
        profile.range_high_midi,
        profile.voiced_ratio * 100.0,
    )
    return profile


async def analyze_with_separation(
    audio_path: str | Path,
    separator,  # VocalSeparator | None（避免循环导入用鸭子类型）
    f0_confidence: float = 0.6,
) -> tuple[VoiceProfile, bool]:
    """先直接分析；无声帧不足且有 separator 时分离人声后再分析。

    Returns:
        (profile, separation_used)：separation_used=True 表示走了 demucs 分离链路。

    Raises:
        VoiceAnalysisError: 无 separator 时直接分析失败原样抛出；
            有 separator 时分离后再分析仍失败也抛出。
        SeparationError: 分离引擎未就绪/子进程失败（separator 为 None 时不会发生）。
    """
    try:
        profile = analyze_pitch(audio_path, f0_confidence)
        return profile, False
    except VoiceAnalysisError as direct_error:
        if separator is None:
            raise
        logger.info(
            "Direct analysis failed (%s); falling back to vocal separation first",
            direct_error,
        )
    vocals_path, _accompaniment_path = await separator.separate_vocal_accompaniment(
        str(audio_path)
    )
    profile = analyze_pitch(vocals_path, f0_confidence)
    return profile, True
