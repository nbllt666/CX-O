"""
Task 4「伴奏渲染与混音」单元测试

覆盖：
- mixer：已知 PCM 内容的小 WAV 混合，验证采样率 / 时长 / 增益 / 声道统一 / 防削波
- accompaniment：和弦解析、最小 SMF 结构、依赖缺失逐项报错
- 真实 fluidsynth 渲染：无 fluidsynth 环境或可用 SoundFont 时 skip（原因显式标注）
"""
from __future__ import annotations

import array
import io
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import pytest

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

import workstation.music.accompaniment as accompaniment_module  # noqa: E402
from workstation.music.accompaniment import (  # noqa: E402
    AccompanimentError,
    check_render_dependencies,
    chord_to_midi_notes,
    render_accompaniment,
    score_to_midi_bytes,
)
from workstation.music.mixer import MixerError, mix_wav  # noqa: E402

# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _write_wav(path: Path, samples: list[int], *, rate: int = 44100, channels: int = 1) -> Path:
    """用 wave 模块构造已知 PCM 内容的 16bit WAV"""
    pcm = array.array("h", samples)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return path


def _read_wav(path: Path) -> tuple[list[int], int, int]:
    """读取 WAV 返回 (样本列表, 采样率, 声道数)"""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    pcm = array.array("h")
    pcm.frombytes(raw)
    return list(pcm), rate, channels


_SCORE = {
    "title": "测试歌谱",
    "bpm": 120,
    "melody": [{"pitch": "C4", "beats": 8, "lyric": ""}],
    "chords": [{"chord": "C", "beats": 4}, {"chord": "G7", "beats": 4}],
}

# ---------------------------------------------------------------------------
# mixer 测试
# ---------------------------------------------------------------------------


class TestMixer:
    def test_mix_length_rate_and_values(self, tmp_path):
        """长度以较长者为准 + 增益正确 + 采样率统一 44100"""
        vocal = _write_wav(tmp_path / "v.wav", [1000] * 1000)
        acc = _write_wav(tmp_path / "a.wav", [500] * 2000)
        out = mix_wav(vocal, acc, tmp_path / "out.wav", vocal_gain=1.0, accompaniment_gain=0.8)

        samples, rate, channels = _read_wav(out)
        assert rate == 44100
        assert channels == 1  # 两路均单声道 → 单声道
        assert len(samples) == 2000  # 以较长者为准
        assert samples[0] == 1000 + 400  # 500 * 0.8
        assert samples[999] == 1400
        assert samples[1500] == 400  # 歌声结束后仅伴奏（短者不补位）

    def test_mix_clip_prevents_overflow(self, tmp_path):
        """PCM16 相加溢出时 clip 到 32767，不削波翻转"""
        vocal = _write_wav(tmp_path / "v.wav", [30000] * 64)
        acc = _write_wav(tmp_path / "a.wav", [30000] * 64)
        out = mix_wav(vocal, acc, tmp_path / "out.wav")
        samples, _, _ = _read_wav(out)
        assert samples == [32767] * 64

    def test_mix_clip_negative(self, tmp_path):
        vocal = _write_wav(tmp_path / "v.wav", [-30000] * 32)
        acc = _write_wav(tmp_path / "a.wav", [-30000] * 32)
        out = mix_wav(vocal, acc, tmp_path / "out.wav")
        samples, _, _ = _read_wav(out)
        assert samples == [-32768] * 32

    def test_mix_vocal_gain(self, tmp_path):
        vocal = _write_wav(tmp_path / "v.wav", [1000] * 100)
        acc = _write_wav(tmp_path / "a.wav", [0] * 100)
        out = mix_wav(vocal, acc, tmp_path / "out.wav", vocal_gain=2.0)
        samples, _, _ = _read_wav(out)
        assert samples == [2000] * 100

    def test_mix_mono_with_stereo_outputs_stereo(self, tmp_path):
        """单声道 + 立体声 → 立体声输出，单声道复制到双声道"""
        vocal = _write_wav(tmp_path / "v.wav", [100] * 50, channels=1)
        acc = _write_wav(tmp_path / "a.wav", [10, 20] * 50, channels=2)
        out = mix_wav(vocal, acc, tmp_path / "out.wav")
        samples, _, channels = _read_wav(out)
        assert channels == 2
        assert len(samples) == 100  # 50 帧 x 2 声道
        assert samples[0] == 110  # 左: 100 + 10
        assert samples[1] == 120  # 右: 100 + 20

    def test_mix_resamples_to_44100(self, tmp_path):
        """非 44100 输入重采样统一，长度按比例换算"""
        vocal = _write_wav(tmp_path / "v.wav", [800] * 200, rate=44100)
        acc = _write_wav(tmp_path / "a.wav", [200] * 100, rate=22050)
        out = mix_wav(vocal, acc, tmp_path / "out.wav")
        samples, rate, _ = _read_wav(out)
        assert rate == 44100
        assert len(samples) == 200  # 22050Hz x 100 帧 → 44100Hz x 200 帧
        assert samples[0] == 1000

    def test_missing_input_raises(self, tmp_path):
        acc = _write_wav(tmp_path / "a.wav", [0] * 16)
        with pytest.raises(MixerError, match="不存在"):
            mix_wav(tmp_path / "no.wav", acc, tmp_path / "out.wav")

    def test_unsupported_bit_width_raises(self, tmp_path):
        """8bit WAV 明确报错（仅支持 16bit PCM）"""
        bad = tmp_path / "bad.wav"
        with wave.open(str(bad), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(1)
            wf.setframerate(44100)
            wf.writeframes(b"\x80" * 32)
        ok = _write_wav(tmp_path / "ok.wav", [0] * 16)
        with pytest.raises(MixerError, match="16bit"):
            mix_wav(bad, ok, tmp_path / "out.wav")


# ---------------------------------------------------------------------------
# accompaniment：和弦解析
# ---------------------------------------------------------------------------


class TestChordParse:
    def test_major_triad(self):
        assert chord_to_midi_notes("C") == [48, 52, 55]  # C3 E3 G3

    def test_minor_triad(self):
        assert chord_to_midi_notes("Am") == [57, 60, 64]  # A3 C4 E4

    def test_dominant7_uses_major_triad(self):
        assert chord_to_midi_notes("G7") == [55, 59, 62]  # G3 B3 D4

    def test_sharp_minor(self):
        assert chord_to_midi_notes("F#m") == [54, 57, 61]  # F#3 A3 C#4

    def test_flat_major(self):
        assert chord_to_midi_notes("Bbmaj7") == [58, 62, 65]  # Bb3 D4 F4

    def test_dim_and_aug(self):
        assert chord_to_midi_notes("Bdim") == [59, 62, 65]
        assert chord_to_midi_notes("Caug") == [48, 52, 56]

    def test_sus4(self):
        assert chord_to_midi_notes("Dsus4") == [50, 55, 57]  # D3 G3 A3

    def test_slash_chord_takes_upper_part(self):
        assert chord_to_midi_notes("C/E") == [48, 52, 55]

    def test_invalid_root_raises(self):
        with pytest.raises(ValueError, match="非法和弦标记"):
            chord_to_midi_notes("H")

    def test_unknown_quality_raises(self):
        with pytest.raises(ValueError, match="无法识别的和弦性质"):
            chord_to_midi_notes("Cxyz")

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="非法和弦标记"):
            chord_to_midi_notes("")


# ---------------------------------------------------------------------------
# accompaniment：最小 SMF 结构
# ---------------------------------------------------------------------------


class TestMidiBytes:
    """SMF format 1 结构（_SCORE 为 v1 裸 dict，无 accompaniment_tracks → 仅元轨）"""

    def test_smf_header(self):
        data = score_to_midi_bytes(_SCORE)
        assert data[:4] == b"MThd"
        assert int.from_bytes(data[4:8], "big") == 6  # header 长度
        # format 1 / 单轨（仅元轨，_SCORE 无 accompaniment_tracks）/ division 480
        assert data[8:14] == b"\x00\x01\x00\x01\x01\xe0"

    def test_smf_track_layout(self):
        """元轨：tempo meta + 拍号 meta + EOT（无音符、无 program change）"""
        data = score_to_midi_bytes(_SCORE)
        assert data[14:18] == b"MTrk"
        track_len = int.from_bytes(data[18:22], "big")
        assert track_len == len(data) - 22
        track = data[22:]
        # 速度元事件：bpm120 → 500000 微秒/四分音符
        assert track[:4] == b"\x00\xff\x51\x03"
        assert track[4:7] == (500000).to_bytes(3, "big")
        # 拍号元事件紧随（非 program change）
        assert track[7:11] == b"\x00\xff\x58\x04"
        # 音轨结束
        assert track.endswith(b"\x00\xff\x2f\x00")

    def test_no_notes_for_v1_score_without_tracks(self):
        """_SCORE 无 accompaniment_tracks → 元轨无 Note On/Off"""
        track = score_to_midi_bytes(_SCORE)[22:]
        assert b"\x90" not in track  # 无 Note On
        assert b"\x80" not in track  # 无 Note Off

    def test_empty_chords_still_valid_smf(self):
        score = {**_SCORE, "chords": []}
        data = score_to_midi_bytes(score)
        assert data[:4] == b"MThd"
        assert data.endswith(b"\x00\xff\x2f\x00")

    def test_invalid_bpm_raises(self):
        with pytest.raises(ValueError, match="bpm"):
            score_to_midi_bytes({**_SCORE, "bpm": 0})


# ---------------------------------------------------------------------------
# accompaniment：依赖缺失逐项报错
# ---------------------------------------------------------------------------


class TestDependencyErrors:
    _MISSING_CMD = "fluidsynth-definitely-not-exists-cxo-task4"

    def test_missing_soundfont_message(self, tmp_path):
        fake_sf = str(tmp_path / "missing.sf2")
        with pytest.raises(AccompanimentError) as exc_info:
            render_accompaniment(_SCORE, str(tmp_path / "out.wav"), soundfont_path=fake_sf)
        message = str(exc_info.value)
        assert "SoundFont" in message
        assert fake_sf in message  # 缺失项含 soundfont 路径

    def test_missing_fluidsynth_message(self, tmp_path):
        sf = tmp_path / "ok.sf2"
        sf.write_bytes(b"fake-soundfont")
        with pytest.raises(AccompanimentError) as exc_info:
            render_accompaniment(
                _SCORE,
                str(tmp_path / "out.wav"),
                soundfont_path=str(sf),
                fluidsynth_cmd=self._MISSING_CMD,
            )
        message = str(exc_info.value)
        assert "fluidsynth" in message
        assert "PATH" in message  # 明确提示 PATH 中找不到

    def test_both_missing_lists_all_items(self, tmp_path):
        """soundfont 与 fluidsynth 同时缺失时逐项列出"""
        fake_sf = str(tmp_path / "missing.sf2")
        with pytest.raises(AccompanimentError) as exc_info:
            render_accompaniment(
                _SCORE,
                str(tmp_path / "out.wav"),
                soundfont_path=fake_sf,
                fluidsynth_cmd=self._MISSING_CMD,
            )
        message = str(exc_info.value)
        assert "SoundFont" in message and fake_sf in message
        assert "fluidsynth" in message and "PATH" in message

    def test_check_render_dependencies_empty_soundfont(self):
        problems = check_render_dependencies("", self._MISSING_CMD)
        assert len(problems) == 2  # 未配置 soundfont + fluidsynth 缺失


# ---------------------------------------------------------------------------
# 真实 fluidsynth 渲染（无环境时 skip）
# ---------------------------------------------------------------------------

_TEST_SOUNDFONT = os.environ.get("CXO_TEST_SOUNDFONT", "")
_HAS_FLUIDSYNTH = shutil.which("fluidsynth") is not None
_HAS_SOUNDFONT = bool(_TEST_SOUNDFONT) and os.path.isfile(_TEST_SOUNDFONT)


@pytest.mark.skipif(
    not (_HAS_FLUIDSYNTH and _HAS_SOUNDFONT),
    reason="无 fluidsynth 环境或可用 SoundFont（CXO_TEST_SOUNDFONT 未配置），跳过真实渲染测试",
)
def test_render_with_real_fluidsynth(tmp_path):
    out = Path(
        render_accompaniment(
            _SCORE, str(tmp_path / "acc.wav"), soundfont_path=_TEST_SOUNDFONT
        )
    )
    assert out.is_file() and out.stat().st_size > 44
    _, rate, _ = _read_wav(out)
    assert rate == 44100


# ---------------------------------------------------------------------------
# render_accompaniment 成功路径与子进程失败（mock fluidsynth，免真实依赖）
# ---------------------------------------------------------------------------


class TestRenderAccompanimentMocked:
    """render_accompaniment 子进程交互路径（mock subprocess.run + shutil.which）

    Task 8 补充：真实 fluidsynth 部署验证属 Task 11，本组用 mock 钉住
    「配置正确 soundfont → fluidsynth 命令行契约 → 旁路 midi 落盘 → 产出 WAV」
    的代码路径正确性，以及非 0 退出 / 空输出 / 超时三类失败分支。
    """

    @staticmethod
    def _wav_bytes(frames: int = 100, rate: int = 44100) -> bytes:
        """构造最小合法 16bit 单声道 WAV 字节（模拟 fluidsynth 产物）"""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b"\x00\x00" * frames)
        return buf.getvalue()

    def _patch_fluidsynth_available(self, monkeypatch) -> None:
        """mock fluidsynth 可在 PATH 中找到（绕过依赖缺失前置检查）"""
        monkeypatch.setattr(accompaniment_module.shutil, "which", lambda cmd: f"/usr/bin/{cmd}")

    def test_render_success_invokes_fluidsynth_and_writes_midi(self, tmp_path, monkeypatch):
        """配置正确 soundfont + mock fluidsynth 产出 WAV → 返回路径、调用参数与旁路 midi 落盘正确"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"
        wav_bytes = self._wav_bytes()

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            out.write_bytes(wav_bytes)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        result = render_accompaniment(_SCORE, str(out), soundfont_path=str(sf))

        assert result == str(out)
        assert out.is_file() and out.stat().st_size > 44
        # 旁路 midi 落盘且为合法 SMF（保留便于排查）
        midi = out.with_suffix(".mid")
        assert midi.is_file()
        assert midi.read_bytes()[:4] == b"MThd"
        # 调用参数钉住 fluidsynth 命令行契约：fluidsynth -ni -F <wav> -r <rate> <sf> <mid>
        # （fluidsynth 2.5+ 要求选项在位置参数之前，该顺序向后兼容 2.4 及更早版本）
        cmd = captured["cmd"]
        assert cmd[0] == "fluidsynth"
        assert cmd[1] == "-ni"
        assert str(sf) in cmd
        assert str(midi) in cmd
        assert "-F" in cmd and str(out) in cmd
        assert "-r" in cmd and "44100" in cmd

    def test_render_success_custom_sample_rate(self, tmp_path, monkeypatch):
        """自定义 sample_rate 透传到 -r 参数"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            out.write_bytes(self._wav_bytes(rate=48000))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        render_accompaniment(_SCORE, str(out), soundfont_path=str(sf), sample_rate=48000)
        assert "48000" in captured["cmd"]

    def test_render_failure_nonzero_returncode(self, tmp_path, monkeypatch):
        """fluidsynth 返回非 0 → AccompanimentError 含退出码与 stderr 详情"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                args=cmd, returncode=2, stdout="", stderr="boom: bad soundfont"
            )

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        with pytest.raises(AccompanimentError, match="退出码 2") as exc_info:
            render_accompaniment(_SCORE, str(out), soundfont_path=str(sf))
        assert "boom" in str(exc_info.value)

    def test_render_failure_empty_output(self, tmp_path, monkeypatch):
        """fluidsynth 退出码 0 但未产出有效 WAV → AccompanimentError"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        with pytest.raises(AccompanimentError, match="未产出有效 WAV"):
            render_accompaniment(_SCORE, str(out), soundfont_path=str(sf))

    def test_render_timeout(self, tmp_path, monkeypatch):
        """fluidsynth 子进程超时 → AccompanimentError 含超时秒数"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-sf2")
        out = tmp_path / "acc.wav"

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=0.01)

        self._patch_fluidsynth_available(monkeypatch)
        monkeypatch.setattr(accompaniment_module.subprocess, "run", fake_run)

        with pytest.raises(AccompanimentError, match="超时"):
            render_accompaniment(_SCORE, str(out), soundfont_path=str(sf), timeout=0.01)
