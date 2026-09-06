"""
Task 3「mixer 多轨混音」单元测试（change-id: enhance-cover-pitch-analysis-duet SubTask 3.4）

覆盖 mix_tracks：
- 三轨加权和（各轨增益）、长度取最长、短轨补静音
- 削波防护（超 0dB 输入 → clip 到 PCM16 边界，正负两向）
- 空 tracks / 文件缺失 / 增益非法 / 条目格式非法 → ValueError 可读
- 重采样统一 44100、自定义采样率、单声道+立体声 → 立体声（单声道复制）
- mix_wav 回归锚点（签名/行为零改动；全量回归跑 test_accompaniment_mixer.py）
"""
from __future__ import annotations

import array
import math
import os
import struct
import sys
import wave
from pathlib import Path

import pytest

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from workstation.music.mixer import (  # noqa: E402
    DEFAULT_SAMPLE_RATE,
    MixerError,
    mix_tracks,
    mix_wav,
)


def _make_wav(
    path: Path,
    samples: list[int],
    *,
    rate: int = 44100,
    channels: int = 1,
) -> Path:
    """用 wave 模块构造已知 PCM 内容的 16bit WAV。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = array.array("h", samples)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return path


def _read_wav(path: Path) -> tuple[list[int], int, int]:
    """读取 WAV 返回（样本列表, 采样率, 声道数）。"""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    pcm = array.array("h")
    pcm.frombytes(raw)
    return list(pcm), rate, channels


def _sine(seconds: float, freq: float, *, rate: int = 44100, amplitude: float = 0.2) -> list[int]:
    """合成正弦样本列表（测试输入用）。"""
    n = int(round(seconds * rate))
    step = 2.0 * math.pi * freq / rate
    scale = amplitude * 32767.0
    return [int(scale * math.sin(step * i)) for i in range(n)]


class TestMixTracks:
    def test_three_track_weighted_sum(self, tmp_path):
        """三轨加权和：Σ sample_i * gain_i，样本值逐点可验证"""
        t1 = _make_wav(tmp_path / "t1.wav", [1000] * 100)
        t2 = _make_wav(tmp_path / "t2.wav", [500] * 200)
        t3 = _make_wav(tmp_path / "t3.wav", [200] * 300)
        out = mix_tracks([(t1, 1.0), (t2, 0.8), (t3, 0.5)], tmp_path / "out.wav")

        samples, rate, channels = _read_wav(out)
        assert rate == DEFAULT_SAMPLE_RATE
        assert channels == 1  # 全部单声道 → 单声道输出
        assert len(samples) == 300  # 长度取最长轨
        assert samples[0] == 1000 + 500 * 0.8 + 200 * 0.5  # 三轨叠加
        assert samples[99] == 1000 + 400 + 100
        assert samples[150] == 400 + 100  # t1 已结束（补静音），t2/t3 叠加
        assert samples[250] == 100  # 仅 t3（t2 亦结束）

    def test_clip_prevents_overflow_three_tracks(self, tmp_path):
        """三轨 30000 叠加 90000 → clip 到 32767，不削波翻转"""
        tracks = [
            _make_wav(tmp_path / f"t{i}.wav", [30000] * 64) for i in range(3)
        ]
        out = mix_tracks([(p, 1.0) for p in tracks], tmp_path / "out.wav")
        samples, _, _ = _read_wav(out)
        assert samples == [32767] * 64

    def test_clip_negative(self, tmp_path):
        """负向 clip：-30000 × 3 → -32768"""
        tracks = [
            _make_wav(tmp_path / f"t{i}.wav", [-30000] * 32) for i in range(3)
        ]
        out = mix_tracks([(p, 1.0) for p in tracks], tmp_path / "out.wav")
        samples, _, _ = _read_wav(out)
        assert samples == [-32768] * 32

    def test_resamples_all_tracks_to_target_rate(self, tmp_path):
        """非 44100 轨线性插值重采样统一，长度按比例换算"""
        t1 = _make_wav(tmp_path / "t1.wav", [800] * 200, rate=44100)
        t2 = _make_wav(tmp_path / "t2.wav", [200] * 100, rate=22050)
        out = mix_tracks([(t1, 1.0), (t2, 1.0)], tmp_path / "out.wav")
        samples, rate, _ = _read_wav(out)
        assert rate == 44100
        assert len(samples) == 200  # 22050Hz×100 帧 → 44100Hz×200 帧
        assert samples[0] == 1000  # 800 + 200

    def test_custom_sample_rate(self, tmp_path):
        """sample_rate 参数透传：全部轨重采样至目标率"""
        t1 = _make_wav(tmp_path / "t1.wav", [1000] * 441, rate=44100)
        t2 = _make_wav(tmp_path / "t2.wav", [0] * 441, rate=44100)
        out = mix_tracks([(t1, 1.0), (t2, 1.0)], tmp_path / "out.wav", sample_rate=22050)
        samples, rate, _ = _read_wav(out)
        assert rate == 22050
        assert len(samples) == 220  # 441 帧 @44100 → 220 帧 @22050（含尾点插值）

    def test_mono_with_stereo_outputs_stereo(self, tmp_path):
        """任一轨立体声 → 立体声输出；单声道轨复制为双声道（mix_wav 同语义）"""
        mono1 = _make_wav(tmp_path / "m1.wav", [100] * 50)
        mono2 = _make_wav(tmp_path / "m2.wav", [30] * 50)
        stereo = _make_wav(tmp_path / "s.wav", [10, 20] * 50, channels=2)
        out = mix_tracks([(mono1, 1.0), (mono2, 1.0), (stereo, 1.0)], tmp_path / "out.wav")
        samples, _, channels = _read_wav(out)
        assert channels == 2
        assert len(samples) == 100  # 50 帧 × 2 声道
        assert samples[0] == 100 + 30 + 10  # 左
        assert samples[1] == 100 + 30 + 20  # 右（单声道复制）

    def test_empty_tracks_raises_valueerror(self):
        with pytest.raises(ValueError, match="不能为空"):
            mix_tracks([], "whatever.wav")

    def test_missing_file_raises_valueerror(self, tmp_path):
        ok = _make_wav(tmp_path / "ok.wav", [0] * 16)
        with pytest.raises(ValueError, match="不存在"):
            mix_tracks([(tmp_path / "no.wav", 1.0), (ok, 1.0)], tmp_path / "out.wav")

    def test_invalid_gain_raises_valueerror(self, tmp_path):
        ok = _make_wav(tmp_path / "ok.wav", [0] * 16)
        for bad in (-0.5, float("nan"), float("inf"), True):
            with pytest.raises(ValueError, match="增益非法"):
                mix_tracks([(ok, bad)], tmp_path / "out.wav")

    def test_malformed_entry_raises_valueerror(self, tmp_path):
        ok = _make_wav(tmp_path / "ok.wav", [0] * 16)
        with pytest.raises(ValueError, match="格式非法"):
            mix_tracks([(ok,)], tmp_path / "out.wav")  # type: ignore[list-item]

    def test_unsupported_bit_width_still_mixer_error(self, tmp_path):
        """格式类错误保持 MixerError（空轨/缺失才是 ValueError 契约）"""
        bad = tmp_path / "bad.wav"
        with wave.open(str(bad), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(1)
            wf.setframerate(44100)
            wf.writeframes(b"\x80" * 32)
        ok = _make_wav(tmp_path / "ok.wav", [0] * 16)
        with pytest.raises(MixerError, match="16bit"):
            mix_tracks([(bad, 1.0), (ok, 1.0)], tmp_path / "out.wav")


class TestMixWavRegressionAnchor:
    """mix_wav 签名/行为锚点（全量回归另跑 test_accompaniment_mixer.py）"""

    def test_mix_wav_two_track_semantics_unchanged(self, tmp_path):
        """既有两轨语义抽查：增益/长度取长/补静音数值与 Task 4 测试同口径"""
        vocal = _make_wav(tmp_path / "v.wav", [1000] * 1000)
        acc = _make_wav(tmp_path / "a.wav", [500] * 2000)
        out = mix_wav(vocal, acc, tmp_path / "out.wav", vocal_gain=1.0, accompaniment_gain=0.8)
        samples, rate, channels = _read_wav(out)
        assert rate == 44100
        assert channels == 1
        assert len(samples) == 2000
        assert samples[0] == 1000 + 400
        assert samples[1500] == 400

    def test_mix_wav_signature_rejects_track_list(self, tmp_path):
        """mix_wav 保持 (vocal, accompaniment) 位置签名，不接受 tracks 列表"""
        vocal = _make_wav(tmp_path / "v.wav", [100] * 10)
        acc = _make_wav(tmp_path / "a.wav", [100] * 10)
        with pytest.raises(TypeError):
            mix_wav([(vocal, 1.0), (acc, 1.0)], tmp_path / "out.wav")  # type: ignore[arg-type]
