"""
server/services/vad_processor.py 回归测试
VAD 能量检测 + 说话状态机 + 回调触发（仅测 ENERGY 模式，无外部依赖）
"""
import struct

import pytest

from server.services.vad_processor import VADMode, VADProcessor, get_vad_processor


def _samples_energy(amplitude: int, n: int = 480) -> bytes:
    """构造能量为 amplitude^2 的 PCM 音频帧（16bit LE mono）。"""
    return struct.pack(f"<{n}h", *([amplitude] * n))


LOW_SAMPLES = _samples_energy(10)      # 能量 100
HIGH_SAMPLES = _samples_energy(1000)   # 能量 1e6


@pytest.fixture
def vad():
    v = VADProcessor()
    v.set_config({"mode": "energy", "energy_threshold": 500, "sample_rate": 16000})
    return v


class TestConfig:
    def test_mode_parsing(self):
        v = VADProcessor()
        v.set_config({"mode": "energy"})
        assert v.mode == VADMode.ENERGY

    def test_invalid_mode_raises(self):
        v = VADProcessor()
        with pytest.raises(ValueError):
            v.set_config({"mode": "bogus"})

    def test_energy_mode_init_without_webrtc(self, vad):
        # ENERGY 模式不依赖 webrtcvad
        assert vad.mode == VADMode.ENERGY
        assert vad._vad is None


class TestEnergyDetection:
    def test_calculate_energy(self, vad):
        assert vad._calculate_energy(HIGH_SAMPLES) > 500
        assert vad._calculate_energy(LOW_SAMPLES) < 500

    def test_calculate_energy_short_frame(self, vad):
        assert vad._calculate_energy(b"\x00") == 0

    def test_detect_energy_above_threshold(self, vad):
        assert vad._detect_energy(HIGH_SAMPLES) is True
        assert vad._detect_energy(LOW_SAMPLES) is False


class TestStateMachine:
    def test_speech_start_transition(self, vad):
        result = vad.process_audio(HIGH_SAMPLES)
        assert result["is_speaking"] is True
        assert result["state_changed"] is True

    def test_continuous_speech_no_rechange(self, vad):
        vad.process_audio(HIGH_SAMPLES)
        result = vad.process_audio(HIGH_SAMPLES)
        assert result["is_speaking"] is True
        assert result["state_changed"] is False

    def test_silence_ends_speech(self, vad):
        vad.process_audio(HIGH_SAMPLES)
        # 强制设置 last_speech_time 为过去，触发静默判定
        vad._state.last_speech_time = 0
        result = vad.process_audio(LOW_SAMPLES)
        assert result["is_speaking"] is False
        assert result["state_changed"] is True

    def test_frame_count_increments(self, vad):
        vad.process_audio(LOW_SAMPLES)
        vad.process_audio(LOW_SAMPLES)
        assert vad._state.frame_count == 2

    def test_reset(self, vad):
        vad.process_audio(HIGH_SAMPLES)
        assert vad.is_speaking is True
        vad.reset()
        assert vad.is_speaking is False
        assert vad._state.frame_count == 0


class TestCallbacks:
    def test_speech_start_callback(self, vad):
        calls = []
        vad.set_callbacks(on_speech_start=lambda: calls.append("start"))
        vad.process_audio(HIGH_SAMPLES)
        assert calls == ["start"]

    def test_speech_end_callback(self, vad):
        calls = []
        vad.set_callbacks(on_speech_end=lambda: calls.append("end"))
        vad.process_audio(HIGH_SAMPLES)
        vad._state.last_speech_time = 0
        vad.process_audio(LOW_SAMPLES)
        assert calls == ["end"]

    def test_callback_exception_swallowed(self, vad):
        def _boom():
            raise RuntimeError("cb")

        vad.set_callbacks(on_speech_start=_boom)
        result = vad.process_audio(HIGH_SAMPLES)  # 不抛异常
        assert result["is_speaking"] is True


class TestSingleton:
    def test_get_instance(self):
        assert get_vad_processor() is VADProcessor.get_instance()