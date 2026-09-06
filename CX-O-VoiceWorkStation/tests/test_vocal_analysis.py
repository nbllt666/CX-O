"""vocal_analysis 单测（change-id: enhance-cover-pitch-analysis-duet SubTask 1.6）

覆盖：
- 合成正弦波端到端：440Hz（A4）→ profile 断言（median_midi≈69±0.5）
- 静音/无声输入 → VoiceAnalysisError 明确错误
- 纯函数边界：hz_to_midi、compute_profile（置信过滤/P10-P90/voiced_ratio 阈值）
"""
from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from workstation.services.vocal_analysis import (
    _MIN_VOICED_RATIO,
    VoiceAnalysisError,
    VoiceProfile,
    analyze_pitch,
    compute_profile,
    hz_to_midi,
)


def _write_sine(path, freq_hz: float = 440.0, seconds: float = 2.0,
                sr: int = 22050, amplitude: float = 0.5) -> str:
    t = np.arange(int(seconds * sr)) / sr
    y = (amplitude * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32)
    sf.write(str(path), y, sr)
    return str(path)


# ---------------------------------------------------------------------------
# 端到端：合成正弦波
# ---------------------------------------------------------------------------
def test_analyze_pitch_sine_440hz_is_a4(tmp_path):
    audio = _write_sine(tmp_path / "a4.wav", freq_hz=440.0)
    profile = analyze_pitch(audio)
    assert abs(profile.f0_median_midi - 69.0) <= 0.5
    assert abs(profile.f0_median_hz - 440.0) <= 5.0
    assert 0.0 < profile.voiced_ratio <= 1.0
    assert profile.range_low_midi <= profile.f0_median_midi <= profile.range_high_midi
    assert profile.range_span_semitones >= 0.0


def test_analyze_pitch_sine_220hz_is_a3(tmp_path):
    audio = _write_sine(tmp_path / "a3.wav", freq_hz=220.0)
    profile = analyze_pitch(audio)
    assert abs(profile.f0_median_midi - 57.0) <= 0.5


def test_analyze_pitch_silence_raises(tmp_path):
    """全静音：voiced_ratio≈0 → 明确错误而非静默画像。"""
    y = np.zeros(22050, dtype=np.float32)
    path = tmp_path / "silence.wav"
    sf.write(str(path), y, 22050)
    with pytest.raises(VoiceAnalysisError, match="voiced frames"):
        analyze_pitch(path)


def test_analyze_pitch_empty_file_raises(tmp_path):
    path = tmp_path / "empty.wav"
    sf.write(str(path), np.zeros(0, dtype=np.float32), 22050)
    with pytest.raises(VoiceAnalysisError):
        analyze_pitch(path)


def test_analyze_pitch_missing_file_raises(tmp_path):
    with pytest.raises(VoiceAnalysisError, match="not found"):
        analyze_pitch(tmp_path / "nope.wav")


# ---------------------------------------------------------------------------
# 纯函数：hz_to_midi
# ---------------------------------------------------------------------------
def test_hz_to_midi_known_values():
    assert hz_to_midi(440.0) == pytest.approx(69.0)   # A4
    assert hz_to_midi(220.0) == pytest.approx(57.0)   # A3
    assert hz_to_midi(880.0) == pytest.approx(81.0)   # A5
    assert hz_to_midi(261.6256) == pytest.approx(60.0, abs=0.01)  # C4


@pytest.mark.parametrize("bad", [0.0, -1.0, -440.0])
def test_hz_to_midi_non_positive_raises(bad):
    with pytest.raises(ValueError):
        hz_to_midi(bad)


# ---------------------------------------------------------------------------
# 纯函数：compute_profile
# ---------------------------------------------------------------------------
def _synth_frames(values: list[float], probs: list[float]):
    f0 = np.array([v if v > 0 else np.nan for v in values], dtype=float)
    return f0, np.array(probs, dtype=float)


def test_compute_profile_confidence_filter():
    """低置信帧（880Hz/prob=0.2）被阈值 0.6 过滤，只统计高置信 440Hz。"""
    values = [440.0] * 90 + [880.0] * 10
    probs = [0.9] * 90 + [0.2] * 10
    f0, voiced_prob = _synth_frames(values, probs)
    profile = compute_profile(f0, voiced_prob, f0_confidence=0.6)
    assert profile.voiced_ratio == pytest.approx(0.9)
    assert profile.f0_median_hz == pytest.approx(440.0)
    assert profile.f0_median_midi == pytest.approx(69.0, abs=1e-6)
    assert profile.range_low_midi == pytest.approx(69.0, abs=1e-6)
    assert profile.range_high_midi == pytest.approx(69.0, abs=1e-6)
    assert profile.range_span_semitones == pytest.approx(0.0, abs=1e-6)


def test_compute_profile_range_p10_p90_two_octaves():
    """C4/C5 各半：P10≈60、P90≈72，跨度≈12 半音。"""
    values = [261.6256] * 50 + [523.2511] * 50
    probs = [0.9] * 100
    f0, voiced_prob = _synth_frames(values, probs)
    profile = compute_profile(f0, voiced_prob, f0_confidence=0.6)
    assert profile.range_low_midi == pytest.approx(60.0, abs=0.1)
    assert profile.range_high_midi == pytest.approx(72.0, abs=0.1)
    assert profile.range_span_semitones == pytest.approx(12.0, abs=0.2)


def test_compute_profile_all_unvoiced_raises():
    f0, voiced_prob = _synth_frames([np.nan] * 100, [0.0] * 100)
    with pytest.raises(VoiceAnalysisError, match="voiced frames"):
        compute_profile(f0, voiced_prob, f0_confidence=0.6)


def test_compute_profile_below_voiced_ratio_threshold_raises():
    """有效帧占比 0.04 < _MIN_VOICED_RATIO(0.05) → 拒绝分析。"""
    values = [440.0] * 4 + [np.nan] * 96
    probs = [0.9] * 4 + [0.0] * 96
    f0, voiced_prob = _synth_frames(values, probs)
    assert _MIN_VOICED_RATIO == pytest.approx(0.05)
    with pytest.raises(VoiceAnalysisError, match="voiced frames"):
        compute_profile(f0, voiced_prob, f0_confidence=0.6)


def test_compute_profile_empty_frames_raises():
    with pytest.raises(VoiceAnalysisError, match="empty"):
        compute_profile(np.array([], dtype=float), np.array([], dtype=float))


def test_compute_profile_custom_confidence_threshold():
    """阈值 0.3 时低置信 880Hz 帧纳入统计（边界行为可配）。"""
    values = [440.0] * 50 + [880.0] * 50
    probs = [0.9] * 50 + [0.4] * 50
    f0, voiced_prob = _synth_frames(values, probs)
    profile = compute_profile(f0, voiced_prob, f0_confidence=0.3)
    assert profile.voiced_ratio == pytest.approx(1.0)


def test_voice_profile_to_dict_keys():
    profile = VoiceProfile(
        f0_median_hz=440.0, f0_median_midi=69.0, range_low_midi=60.0,
        range_high_midi=72.0, range_span_semitones=12.0, voiced_ratio=0.9,
    )
    d = profile.to_dict()
    assert set(d) == {
        "f0_median_hz", "f0_median_midi", "range_low_midi",
        "range_high_midi", "range_span_semitones", "voiced_ratio",
    }
