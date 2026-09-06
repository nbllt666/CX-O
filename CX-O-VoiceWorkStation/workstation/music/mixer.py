"""
混音器模块：歌声 WAV + 伴奏 WAV → 成品 WAV（标准库 wave + array 实现，零第三方依赖）

统一规则：
- 采样率统一为 44100Hz（输入不一致时做线性插值重采样；本流水线输入天然为 44100，
  重采样仅为兼容兜底）
- 采样位宽要求 16bit PCM（流水线内 fluidsynth / Mock 引擎产物均为 16bit）
- 声道以输入为准统一：两路均单声道 → 单声道输出；否则立体声输出（单声道复制为双声道）
- 长度以较长者为准，短者补静音；逐样本 clip 防削波

多轨扩展（change-id: enhance-cover-pitch-analysis-duet Task 3）：
- mix_tracks(tracks, output_path)：N 轨加权求和混音，重采样/补静音/clip/声道
  语义与 mix_wav 完全一致；mix_wav 签名与行为零改动（song_pipeline 回归保证）
"""
from __future__ import annotations

import array
import math
import os
import wave
from pathlib import Path

# 输出默认采样率（与 spec「输出 44.1kHz WAV」一致）
DEFAULT_SAMPLE_RATE = 44100

_PCM16_MIN = -32768
_PCM16_MAX = 32767


class MixerError(Exception):
    """混音失败（输入文件缺失 / 格式不支持 / 文件损坏），消息含可读原因"""


# ---------------------------------------------------------------------------
# WAV 读取与样本处理
# ---------------------------------------------------------------------------


def _read_wav_pcm16(path: str | os.PathLike) -> tuple[array.array, int, int]:
    """
    读取 WAV 为 16bit PCM 样本（声道交错），返回 (samples, sample_rate, channels)。

    Raises:
        MixerError: 文件不存在、非 WAV、位宽非 16bit 或声道数不支持时
    """
    if not os.path.isfile(path):
        raise MixerError(f"WAV 文件不存在: {path}")
    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except wave.Error as exc:
        raise MixerError(f"无法解析 WAV 文件 {path}: {exc}") from exc
    if width != 2:
        raise MixerError(f"WAV 采样位宽不支持: {path}（{width * 8}bit，仅支持 16bit PCM）")
    if channels not in (1, 2):
        raise MixerError(f"WAV 声道数不支持: {path}（{channels} 声道，仅支持单声道/立体声）")
    # WAV PCM 为小端；目标运行环境（x86/x64）array('h') 本机序即小端
    samples = array.array("h")
    samples.frombytes(raw)
    return samples, rate, channels


def _to_channel_lists(samples: array.array, channels: int) -> list[list[float]]:
    """交错样本拆分为逐声道列表"""
    if channels == 1:
        return [list(samples)]
    return [list(samples[0::2]), list(samples[1::2])]


def _resample_linear(data: list[float], in_rate: int, out_rate: int) -> list[float]:
    """线性插值重采样（兜底路径；in_rate == out_rate 时原样返回）"""
    if in_rate == out_rate or not data:
        return list(data)
    ratio = in_rate / out_rate
    out_len = max(1, int(round(len(data) * out_rate / in_rate)))
    last = len(data) - 1
    out: list[float] = []
    for i in range(out_len):
        pos = i * ratio
        idx = int(pos)
        if idx >= last:
            out.append(float(data[last]))
        else:
            frac = pos - idx
            out.append(data[idx] + (data[idx + 1] - data[idx]) * frac)
    return out


def _clip_pcm16(value: float) -> int:
    """浮点样本四舍五入并截断到 16bit PCM 范围（防削波）"""
    ivalue = int(round(value))
    if ivalue > _PCM16_MAX:
        return _PCM16_MAX
    if ivalue < _PCM16_MIN:
        return _PCM16_MIN
    return ivalue


# ---------------------------------------------------------------------------
# 混音主流程
# ---------------------------------------------------------------------------


def mix_wav(
    vocal_path: str | os.PathLike,
    accompaniment_path: str | os.PathLike,
    output_path: str | os.PathLike,
    *,
    vocal_gain: float = 1.0,
    accompaniment_gain: float = 1.0,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> Path:
    """
    将歌声 WAV 与伴奏 WAV 混音为成品 WAV。

    统一为 sample_rate（默认 44100Hz）/ 16bit PCM；声道以输入为准
    （两路均单声道 → 单声道，否则立体声）；长度以较长者为准，短者补静音；
    逐样本 `vocal*vocal_gain + accompaniment*accompaniment_gain` 并 clip 防削波。

    Args:
        vocal_path: 歌声 WAV 路径
        accompaniment_path: 伴奏 WAV 路径
        output_path: 输出 WAV 路径（父目录自动创建）
        vocal_gain: 歌声增益（默认 1.0）
        accompaniment_gain: 伴奏增益（默认 1.0）
        sample_rate: 输出采样率

    Returns:
        输出 WAV 的 Path

    Raises:
        MixerError: 输入缺失或格式不支持时
    """
    vocal_samples, vocal_rate, vocal_channels = _read_wav_pcm16(vocal_path)
    acc_samples, acc_rate, acc_channels = _read_wav_pcm16(accompaniment_path)

    out_channels = 1 if (vocal_channels == 1 and acc_channels == 1) else 2

    def _prepare(samples: array.array, rate: int, channels: int) -> list[list[float]]:
        per_channel = [_resample_linear(ch, rate, sample_rate) for ch in _to_channel_lists(samples, channels)]
        if out_channels == 2 and channels == 1:
            per_channel = [per_channel[0], list(per_channel[0])]
        return per_channel

    vocal = _prepare(vocal_samples, vocal_rate, vocal_channels)
    acc = _prepare(acc_samples, acc_rate, acc_channels)

    out_len = max(
        (len(ch) for ch in vocal + acc),
        default=0,
    )
    # 短者补静音
    for ch_data in vocal + acc:
        if len(ch_data) < out_len:
            ch_data.extend([0.0] * (out_len - len(ch_data)))

    mixed = array.array("h")
    for i in range(out_len):
        frame = [
            _clip_pcm16(vocal[ch][i] * vocal_gain + acc[ch][i] * accompaniment_gain)
            for ch in range(out_channels)
        ]
        mixed.extend(frame)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(out_channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(mixed.tobytes())
    return out


def mix_tracks(
    tracks: list[tuple[str | os.PathLike, float]],
    output_path: str | os.PathLike,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> Path:
    """
    N 轨加权混音（duet 三轨混音消费，change-id: enhance-cover-pitch-analysis-duet Task 3）。

    策略与 mix_wav 完全一致：全部轨线性插值重采样至 sample_rate、16bit PCM；
    声道以输入为准（全部单声道 → 单声道输出，任一立体声 → 立体声输出，
    单声道轨复制为双声道）；长度以最长轨为准，短者补静音；
    逐样本 `Σ sample_i * gain_i` 加权求和并 clip 防削波。

    Args:
        tracks: [(wav 路径, 增益), ...] 有序轨列表（求和顺序不影响结果）
        output_path: 输出 WAV 路径（父目录自动创建）
        sample_rate: 输出采样率（默认 44100）

    Returns:
        输出 WAV 的 Path

    Raises:
        ValueError: tracks 为空 / 轨条目格式非法 / 增益非法 / 输入文件缺失（可读原因）
        MixerError: 输入非 WAV、位宽非 16bit 或声道数不支持时
    """
    if not tracks:
        raise ValueError("mix_tracks: tracks 不能为空（至少需要一路输入）")

    normalized: list[tuple[str, float]] = []
    for index, entry in enumerate(tracks):
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            raise ValueError(
                f"mix_tracks: 第 {index} 轨格式非法（应为 (路径, 增益) 元组）: {entry!r}"
            )
        path, gain = entry
        if (
            not isinstance(gain, (int, float))
            or isinstance(gain, bool)
            or not math.isfinite(gain)
            or gain < 0
        ):
            raise ValueError(
                f"mix_tracks: 第 {index} 轨增益非法: {gain!r}（必须为 ≥0 的有限数值）"
            )
        if not os.path.isfile(path):
            raise ValueError(f"mix_tracks: 输入 WAV 文件不存在: {path}")
        normalized.append((path, float(gain)))

    # 读取全部轨：[(逐声道样本列表, 采样率, 声道数, 增益)]
    loaded: list[tuple[list[list[float]], int, int, float]] = []
    for path, gain in normalized:
        samples, rate, channels = _read_wav_pcm16(path)
        loaded.append((_to_channel_lists(samples, channels), rate, channels, gain))

    # 声道语义对齐 mix_wav：全部单声道 → 单声道；任一立体声 → 立体声
    out_channels = 1 if all(channels == 1 for _, _, channels, _ in loaded) else 2

    def _prepare(
        ch_lists: list[list[float]], rate: int, channels: int
    ) -> list[list[float]]:
        per_channel = [
            _resample_linear(ch, rate, sample_rate) for ch in ch_lists
        ]
        if out_channels == 2 and channels == 1:
            per_channel = [per_channel[0], list(per_channel[0])]
        return per_channel

    prepared: list[tuple[list[list[float]], float]] = [
        (_prepare(ch_lists, rate, channels), gain)
        for ch_lists, rate, channels, gain in loaded
    ]

    # 长度取最长轨，短者逐声道补静音
    out_len = max(
        (len(ch) for per_channel, _ in prepared for ch in per_channel),
        default=0,
    )
    for per_channel, _gain in prepared:
        for ch_data in per_channel:
            if len(ch_data) < out_len:
                ch_data.extend([0.0] * (out_len - len(ch_data)))

    # 逐样本加权和 + clip 防削波
    mixed = array.array("h")
    for i in range(out_len):
        frame = [
            _clip_pcm16(
                sum(per_channel[ch][i] * gain for per_channel, gain in prepared)
            )
            for ch in range(out_channels)
        ]
        mixed.extend(frame)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(out_channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(mixed.tobytes())
    return out
