"""分析 WAV 文件中的静音段分布。

用于诊断 TTS 合成中"间隔过多"的问题。
静音定义：PCM 振幅绝对值持续低于阈值的连续段。
"""
from __future__ import annotations

import wave
import sys
from pathlib import Path

# 静音阈值（16-bit PCM，绝对值低于此值视为静音）
SILENCE_THRESHOLD = 200  # ~0.6% of max amplitude
# 最小静音段时长（ms），短于此不认为是间隔
MIN_SILENCE_MS = 50


def analyze_wav(path: Path) -> None:
    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        pcm = wf.readframes(n_frames)

    print(f"文件: {path.name}")
    print(f"  通道数: {n_channels}")
    print(f"  位深: {sample_width * 8}-bit")
    print(f"  采样率: {framerate} Hz")
    print(f"  总帧数: {n_frames}")
    print(f"  总时长: {n_frames / framerate:.2f}s")
    print()

    if sample_width != 2:
        print(f"  不支持 {sample_width * 8}-bit，仅支持 16-bit")
        return

    # 解析为 16-bit signed int
    import array
    samples = array.array("h", pcm)
    if n_channels > 1:
        # 只取第一通道
        samples = samples[::n_channels]

    abs_samples = [abs(s) for s in samples]

    # 找静音段
    min_silence_samples = int(framerate * MIN_SILENCE_MS / 1000)
    silence_segments = []
    in_silence = False
    silence_start = 0

    for i, amp in enumerate(abs_samples):
        if amp < SILENCE_THRESHOLD:
            if not in_silence:
                in_silence = True
                silence_start = i
        else:
            if in_silence:
                silence_duration = i - silence_start
                if silence_duration >= min_silence_samples:
                    silence_segments.append((silence_start, i, silence_duration))
                in_silence = False

    # 处理结尾的静音
    if in_silence:
        silence_duration = len(samples) - silence_start
        if silence_duration >= min_silence_samples:
            silence_segments.append((silence_start, len(samples), silence_duration))

    total_silence_samples = sum(seg[2] for seg in silence_segments)
    total_silence_ms = total_silence_samples * 1000 / framerate
    total_silence_s = total_silence_ms / 1000
    speech_samples = len(samples) - total_silence_samples
    speech_s = speech_samples / framerate

    print(f"静音阈值: amplitude < {SILENCE_THRESHOLD}")
    print(f"最小静音段: {MIN_SILENCE_MS}ms")
    print()
    print(f"静音段数: {len(silence_segments)}")
    print(f"总静音时长: {total_silence_s:.2f}s ({total_silence_ms:.0f}ms)")
    print(f"语音时长: {speech_s:.2f}s")
    print(f"静音占比: {total_silence_s / (n_frames / framerate) * 100:.1f}%")
    print()

    if silence_segments:
        print("前 10 个静音段:")
        for i, (start, end, dur) in enumerate(silence_segments[:10]):
            start_ms = start * 1000 / framerate
            end_ms = end * 1000 / framerate
            dur_ms = dur * 1000 / framerate
            print(f"  [{i+1}] {start_ms:.0f}ms - {end_ms:.0f}ms (持续 {dur_ms:.0f}ms)")

        if len(silence_segments) > 10:
            print(f"  ... 共 {len(silence_segments)} 段")

        # 最长的 5 个静音段
        sorted_segs = sorted(silence_segments, key=lambda x: -x[2])[:5]
        print()
        print("最长的 5 个静音段:")
        for i, (start, end, dur) in enumerate(sorted_segs):
            start_ms = start * 1000 / framerate
            end_ms = end * 1000 / framerate
            dur_ms = dur * 1000 / framerate
            print(f"  [{i+1}] {start_ms:.0f}ms - {end_ms:.0f}ms (持续 {dur_ms:.0f}ms)")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = Path("c:/CX-O/.trae/test_reports/audio_sample_orpheus_multilingual.wav")

    if not path.exists():
        print(f"文件不存在: {path}")
        sys.exit(1)

    analyze_wav(path)
