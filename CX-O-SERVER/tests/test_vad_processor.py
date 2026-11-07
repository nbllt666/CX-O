"""
server/services/vad_processor.py 回归测试
VAD 能量检测 + 说话状态机 + 回调触发（仅测 ENERGY 模式，无外部依赖）
"""
import asyncio
import struct
import time

import pytest

from server.services.asr_service import StreamingASRResult
from server.services.vad_processor import (
    VADMode,
    VADProcessor,
    AudioStreamProcessor,
    apply_parallel_config,
    get_parallel_config,
    get_vad_processor,
)


def _samples_energy(amplitude: int, n: int = 480) -> bytes:
    """构造能量为 amplitude^2 的 PCM 音频帧（16bit LE mono）。"""
    return struct.pack(f"<{n}h", *([amplitude] * n))


LOW_SAMPLES = _samples_energy(10)      # 能量 100
HIGH_SAMPLES = _samples_energy(1000)   # 能量 1e6
# 60ms 帧：前 30ms 低幅（静音）+ 后 30ms 高幅（有声），用于暴露「首 30ms 盲区」
MIXED_60MS_SAMPLES = LOW_SAMPLES + HIGH_SAMPLES


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
        # #12: 能量归一化到 [-1,1] 满刻度均方（阈值 500/32768² 同步换算），
        # 判定语义不变，仍保持 high > threshold > low
        assert vad._calculate_energy(HIGH_SAMPLES) > vad.energy_threshold
        assert vad._calculate_energy(LOW_SAMPLES) < vad.energy_threshold
        assert vad._calculate_energy(HIGH_SAMPLES) < 1.0

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


class TestParallelVAD:
    """并行 VAD 一致判停（spec add-parallel-vad-endpoint-veto Task 5，全离线）。"""

    def _make_vad(self, energy_threshold: int = 500) -> VADProcessor:
        """构造 ENERGY 主模式 + 默认并行配置的处理器（不依赖 webrtcvad）。"""
        v = VADProcessor()
        v.set_config({
            "mode": "energy",
            "energy_threshold": energy_threshold,
            "sample_rate": 16000,
        })
        return v

    def test_parallel_gate_off_behaviour_unchanged(self, vad):
        # parallel_gate=False：完全不进入并行分支，时序/字段与旧用例一致
        first = vad.process_audio(HIGH_SAMPLES, parallel_gate=False)
        assert first["is_speaking"] is True
        assert first["state_changed"] is True
        assert first["parallel"] is None
        assert first["end_vetoed"] is False

        vad._state.last_speech_time = 0
        second = vad.process_audio(LOW_SAMPLES, parallel_gate=False)
        assert second["is_speaking"] is False
        assert second["state_changed"] is True
        assert second["parallel"] is None
        assert second["end_vetoed"] is False

    def test_long_pause_not_endpointed(self):
        # 主 VAD 阈值抬高 → 整帧判静默；并行默认能量阈值低 → 整帧判有声。
        # 主静默 + 并行有声时不得翻转 state_changed，只记录 end_vetoed 证据。
        v = self._make_vad(energy_threshold=10_000_000)
        assert v._detect_energy(MIXED_60MS_SAMPLES) is False

        started = v.process_audio(HIGH_SAMPLES, parallel_gate=True)
        assert started["is_speaking"] is True
        assert started["state_changed"] is True

        result = v.process_audio(MIXED_60MS_SAMPLES, parallel_gate=True)
        assert result["is_speaking"] is True
        assert result["state_changed"] is False
        assert result["end_vetoed"] is True
        assert result["parallel"]["is_speech"] is True
        assert v.end_veto_count == 1

    def test_consistent_silence_endpoints_once(self, vad):
        # 两路一致静默超过阈值 → 只翻转一次（第二帧不再 state_changed）
        vad.process_audio(HIGH_SAMPLES, parallel_gate=True)
        assert vad.is_speaking is True

        vad._state.last_speech_time = 0
        vad._parallel.last_speech_time = 0
        first = vad.process_audio(LOW_SAMPLES, parallel_gate=True)
        second = vad.process_audio(LOW_SAMPLES, parallel_gate=True)

        assert first["is_speaking"] is False
        assert first["state_changed"] is True
        assert second["state_changed"] is False
        assert second["is_speaking"] is False

    def test_subframe_vote_scans_whole_frame(self, vad):
        # 注入假并行 VAD：仅第 2 个子帧返回有声。若只扫首 30ms 则 ratio=0 → 判静默；
        # 能判有声即证明整帧子帧都被扫描（60ms → 2 次调用）。
        class _CountingParallelVAD:
            def __init__(self):
                self.calls = 0

            def is_speech(self, sub, sr):
                self.calls += 1
                return self.calls == 2

        fake = _CountingParallelVAD()
        vad.parallel_mode = "webrtc"
        vad.parallel_webrtc_vote_ratio = 0.5
        vad._parallel_vad = fake

        result = vad.process_audio(MIXED_60MS_SAMPLES, parallel_gate=True)
        assert fake.calls == 2
        assert result["parallel"]["is_speech"] is True

    def test_max_utterance_forces_end(self):
        # 有界收尾：超过 max_utterance_ms 即使并行仍判有声也强制翻转一次
        v = self._make_vad()
        v.parallel_max_utterance_ms = 1
        v.process_audio(HIGH_SAMPLES, parallel_gate=True)
        assert v.is_speaking is True

        v._state.speech_start_time = time.time() - 0.05
        result = v.process_audio(HIGH_SAMPLES, parallel_gate=True)
        assert result["state_changed"] is True
        assert result["is_speaking"] is False
        assert result["speech_duration_ms"] == 0

    def test_parallel_config_defaults_match_reasonably(self):
        # 模块级缓存 8 键；enabled=False 影响 __init__ 新建实例；finally 恢复防污染
        cfg = get_parallel_config()
        assert set(cfg) == {
            "enabled",
            "mode",
            "silence_threshold_ms",
            "energy_threshold",
            "subframe_ms",
            "webrtc_vote_ratio",
            "consistency_window_ms",
            "max_utterance_ms",
        }
        try:
            apply_parallel_config({"enabled": False})
            assert VADProcessor().parallel_enabled is False
        finally:
            apply_parallel_config({"enabled": True})

    def test_reset_clears_parallel_state(self, vad):
        vad.process_audio(HIGH_SAMPLES, parallel_gate=True)
        assert vad.is_speaking is True
        assert vad._parallel.is_speech is True

        vad.reset()
        assert vad.is_speaking is False
        assert vad._parallel.is_speech is False
        assert vad._end_vetoed_this_utterance is False


class TestSingleton:
    def test_get_instance(self):
        assert get_vad_processor() is VADProcessor.get_instance()


class _FakeSpeakerStream:
    """返回带 speaker 字段的流式 ASR 假客户端。"""

    def __init__(self, result):
        self.result = result
        self.sent = 0

    async def send_audio_chunk(self, data, is_last=False, client_id=None):
        self.sent += 1
        return True

    async def receive_result(self, timeout=0, client_id=None):
        return self.result

    async def reset(self, client_id=None):
        pass


class TestSpeakerPassthrough:
    """AudioStreamProcessor.process_audio_chunk 对声纹字段的透传断言（Task 4）。"""

    @pytest.mark.asyncio
    async def test_speaker_fields_transduced(self):
        proc = AudioStreamProcessor(client_id="spk-test")
        proc.set_config({"vad": {"mode": "energy", "energy_threshold": 500, "sample_rate": 16000}})
        fake = _FakeSpeakerStream(StreamingASRResult(
            text="你好",
            speaker_id="spk-1",
            speaker_name="阿明",
            speaker_registered=True,
            speaker_conf=0.9,
        ))
        proc.set_asr_client(fake)

        result = await proc.process_audio_chunk(HIGH_SAMPLES)
        asr = result["asr"]
        assert asr is not None
        # 既有字段不受影响
        assert asr["text"] == "你好"
        # 声纹字段完整透传
        assert asr["speaker_id"] == "spk-1"
        assert asr["speaker_name"] == "阿明"
        assert asr["speaker_registered"] is True
        assert asr["speaker_conf"] == 0.9
        # 确有触发发送与接收
        assert fake.sent >= 1

    @pytest.mark.asyncio
    async def test_speaker_fields_defaults_when_absent(self):
        """AppStream 结果缺声纹字段 → 透传默认值，向后兼容。"""
        proc = AudioStreamProcessor(client_id="spk-test2")
        proc.set_config({"vad": {"mode": "energy", "energy_threshold": 500, "sample_rate": 16000}})
        fake = _FakeSpeakerStream(StreamingASRResult(text="你好"))
        proc.set_asr_client(fake)

        result = await proc.process_audio_chunk(HIGH_SAMPLES)
        asr = result["asr"]
        assert asr["speaker_id"] == ""
        assert asr["speaker_name"] == ""
        assert asr["speaker_registered"] is False
        assert asr["speaker_conf"] == 0.0


class _BlockingInterrupt:
    """agent_interrupt 替身：on_asr_partial_result 挂在事件上以模拟排队，可放行。"""

    def __init__(self):
        self.calls = []
        self.gate_open = False

    async def on_asr_partial_result(self, text, is_final=False):
        import asyncio

        while not self.gate_open:
            await asyncio.sleep(0.01)
        self.calls.append(text)
        return {"should_interrupt": False, "should_reply": False}

    async def interrupt_user(self, reply_content=""):
        return True


class _AlwaysFreeSemaphore(asyncio.Semaphore):
    """locked() 恒 False 的信号量替身：让提交端通过超限检查后仍能卡在 acquire。"""

    def locked(self):
        return False


class TestDeferredInterruptEpoch:
    """M：打断判定并发槽排队期间 utterance 收尾 → 过期判定被代际校验丢弃。"""

    def _make_processor(self):
        proc = AudioStreamProcessor(client_id="epoch-test")
        proc.set_config({"vad": {"mode": "energy", "energy_threshold": 500, "sample_rate": 16000}})
        return proc

    @pytest.mark.asyncio
    async def test_stale_interrupt_dropped_after_epoch_advance(self, monkeypatch):
        # 场景还原：partial 高频帧的判定任务通过 locked() 检查后卡在 await acquire；
        # 本句收尾推进代际；任务最终拿到槽位时校验失败 → 丢弃，不执行 interrupt_user。
        import asyncio
        import time as _time

        from server.services import vad_processor as vp_mod

        # 占住可控信号量：提交端 locked() 永远放行，但唯一槽被主协程持有 → 任务挂起在 acquire
        sem = _AlwaysFreeSemaphore(1)
        await sem.acquire()
        monkeypatch.setattr(vp_mod, "_interrupt_sem", sem)
        monkeypatch.setattr(vp_mod, "_interrupt_sem_loop", asyncio.get_running_loop())

        proc = self._make_processor()
        interrupt = _BlockingInterrupt()
        interrupt.gate_open = True  # 校验一旦通过应立即执行（本测试期待其不通过）
        proc.set_agent_interrupt(interrupt)
        proc.set_asr_client(_FakeSpeakerStream(StreamingASRResult(text="帮我查一下")))

        # 第1帧：提交打断判定任务（捕获 epoch=0，任务随即挂起在 acquire 上）
        await proc.process_audio_chunk(HIGH_SAMPLES)
        assert interrupt.calls == []  # 未执行

        # 本句收尾：推进代际（此刻卡在 acquire 的判定已成过期）
        proc._utterance_epoch += 1

        # 归还槽位，让任务完成 acquire → 触发代际校验 → 丢弃
        sem.release()
        await asyncio.sleep(0.05)
        assert interrupt.calls == []          # 过期判定被丢弃
        assert sem._value >= 1                # 槽位已正常归还

    @pytest.mark.asyncio
    async def test_fresh_interrupt_not_dropped(self):
        """代际一致（同句）时判定正常执行，不误伤。"""
        import asyncio

        proc = self._make_processor()
        interrupt = _BlockingInterrupt()
        proc.set_agent_interrupt(interrupt)
        proc.set_asr_client(_FakeSpeakerStream(StreamingASRResult(text="在吗")))

        await proc.process_audio_chunk(HIGH_SAMPLES)
        interrupt.gate_open = True
        await asyncio.sleep(0.1)

        assert interrupt.calls == ["在吗"]

    @pytest.mark.asyncio
    async def test_release_task_tracked_by_module_set(self):
        """L：release_audio_stream_processor 的后台关闭任务保存进模块级强引用集。"""
        from server.services import vad_processor as vp_mod

        proc = self._make_processor()
        vp_mod.get_audio_stream_processor("rel-test")
        vp_mod._client_audio_stream_processors["rel-test"] = proc

        vp_mod.release_audio_stream_processor("rel-test")

        try:
            await asyncio_sleep(0.02)
            # 处理器已从注册表移除（关闭任务已在强引用保护下调度并执行）
            await asyncio_sleep(0.05)
            assert "rel-test" not in vp_mod._client_audio_stream_processors
        finally:
            for t in list(vp_mod._release_tasks):
                t.cancel()


class _FakeContextStream:
    """记录 is_last 与 reset 次数，用于验证 SILENT 保留 ASR 上下文。"""

    def __init__(self, result=None):
        self.result = result
        self.last_flags = []
        self.reset_count = 0

    async def send_audio_chunk(self, data, is_last=False, client_id=None):
        self.last_flags.append(is_last)
        return True

    async def receive_result(self, timeout=0, client_id=None):
        return self.result

    async def reset(self, client_id=None):
        self.reset_count += 1


class TestPreserveAsrContext:
    """SILENT 判定：不发送 is_last、不 reset 流式 ASR（保留识别上下文）。"""

    def _make_proc(self, client_id: str):
        proc = AudioStreamProcessor(client_id=client_id)
        proc.set_config({"vad": {"mode": "energy", "energy_threshold": 500, "sample_rate": 16000}})
        fake = _FakeContextStream()
        proc.set_asr_client(fake)
        return proc, fake

    def _force_end(self, proc):
        """把最后一次说话时间推到很久以前，使下一静默帧立即满足判停阈值。"""
        proc.vad._state.last_speech_time = 0
        proc.vad._parallel.last_speech_time = 0

    @pytest.mark.asyncio
    async def test_preserve_skips_is_last_and_reset(self):
        proc, fake = self._make_proc("silent-keep")
        await proc.process_audio_chunk(HIGH_SAMPLES)
        self._force_end(proc)
        await proc.process_audio_chunk(LOW_SAMPLES, preserve_asr_context=True)

        assert True not in fake.last_flags
        assert fake.reset_count == 0

    @pytest.mark.asyncio
    async def test_default_still_sends_is_last_and_resets(self):
        proc, fake = self._make_proc("silent-reset")
        await proc.process_audio_chunk(HIGH_SAMPLES)
        self._force_end(proc)
        await proc.process_audio_chunk(LOW_SAMPLES)

        assert True in fake.last_flags
        assert fake.reset_count == 1


def asyncio_sleep(duration):
    import asyncio

    return asyncio.sleep(duration)