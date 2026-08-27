"""TTSService 统一 Qwen3 编排 Mock E2E 测试。

Task 7 闭合判据：Qwen3 TTS 为唯一合成路径，旧 F5/Orpheus 引擎已彻底移除。

用 MockProvider 注入 Qwen3 Provider + monkeypatch 情感指令生成，验证统一编排入口
全部走 Qwen3，覆盖：

- 非流式 synthesize：剥离指令、生成指令、refs 归一化、委托 Provider、返回音频
- 无参考音频合成（refs 为空列表）
- 流式 synthesize_stream：chunk 顺序与 is_final 保持
- 细粒度流式 synthesize_stream_fine：token 流分块 → 逐段合成 → 末尾 final
- 情感方法 synthesize_with_emotions / synthesize_stream_with_emotions 委托 Qwen3
- _build_ref_ids 五来源归一化（refs / ref_asset_id / ref_audio 资产ID / base64 / path）
- _build_qwen3_request defaults 读取与 kwargs 覆盖

运行：python -m pytest tests/test_tts_service_qwen3.py -q
"""
import io
import wave

import pytest

from server import ref_audio_store
from server.services import tts_service as tts_svc_mod
from server.services.tts_service import TTSService, TTSServiceUnavailableError
from server.qwen3_tts_provider import AudioChunk, SynthesisResponse


def _wav_bytes(sample_rate: int = 24000, channels: int = 1, duration: float = 3.0) -> bytes:
    """生成一段 WAV 字节（PCM 静音）。"""
    buf = io.BytesIO()
    nframes = int(sample_rate * duration)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * nframes)
    return buf.getvalue()


@pytest.fixture
def isolated_store(tmp_path):
    """隔离参考音频资产目录并清理当前指针。"""
    ref_audio_store._set_assets_dir(tmp_path)
    ref_audio_store.clear_current()
    yield tmp_path
    ref_audio_store.clear_current()
    ref_audio_store._set_assets_dir(None)


# ============================================================================
# Mock Provider
# ============================================================================
class MockProvider:
    """记录请求并返回固定音频/流的 Qwen3 Provider 替身。"""

    def __init__(self, audio: bytes = b"RIFF....WAV"):
        self.audio = audio
        self.requests: list = []
        self.stream_chunks = [
            AudioChunk(index=0, data=b"pcm1", format="wav", sample_rate=24000,
                       is_start=True, is_final=False),
            AudioChunk(index=1, data=b"pcm2", format="wav", sample_rate=24000,
                       is_start=False, is_final=True),
        ]

    async def synthesize(self, req):
        self.requests.append(("synthesize", req))
        return SynthesisResponse(audio=self.audio, format="wav", sample_rate=24000,
                                 channels=1, refs_used=list(req.refs))

    async def synthesize_stream(self, req):
        self.requests.append(("synthesize_stream", req))
        for chunk in self.stream_chunks:
            yield chunk


def _svc(provider=None, **kw):
    return TTSService(
        qwen3_enabled=True,
        qwen3_provider=provider or MockProvider(),
        emotion_instruction_enabled=True,
        **kw
    )


@pytest.fixture
def mock_instruction(monkeypatch):
    """固定指令生成器：_gen_instruction 返回固定文本，strip_instruction 恒等。"""
    monkeypatch.setattr(tts_svc_mod, "strip_instruction", lambda t: t)
    class _Inst:
        text = "用俏皮的语气说"
    async def _fake_gen(text):
        return _Inst()
    monkeypatch.setattr(tts_svc_mod, "generate_instruction", _fake_gen)
    return None


# ================================================================== H10：未启用守卫
class TestQwen3DisabledGuard:
    """H10：qwen3 未启用 / provider 缺失时三入口抛明确异常 + 构造期校验。"""

    def _disabled_svc(self, **kw):
        return TTSService(qwen3_enabled=False, qwen3_provider=None, **kw)

    def test_constructor_rejects_enabled_without_provider(self):
        # 构造期：标志启用但 provider 为 None → 立即 ValueError
        with pytest.raises(ValueError, match="provider"):
            TTSService(qwen3_enabled=True, qwen3_provider=None)

    @pytest.mark.asyncio
    async def test_synthesize_raises_unavailable(self):
        svc = self._disabled_svc()
        with pytest.raises(TTSServiceUnavailableError):
            await svc.synthesize("你好")

    @pytest.mark.asyncio
    async def test_synthesize_stream_raises_unavailable(self):
        svc = self._disabled_svc()
        with pytest.raises(TTSServiceUnavailableError):
            async for _ in svc.synthesize_stream("你好"):
                pass

    @pytest.mark.asyncio
    async def test_synthesize_stream_fine_raises_unavailable(self):
        async def _tokens():
            yield "你好"

        svc = self._disabled_svc()
        with pytest.raises(TTSServiceUnavailableError):
            async for _ in svc.synthesize_stream_fine(_tokens()):
                pass

    @pytest.mark.asyncio
    async def test_enabled_with_provider_still_works(self, mock_instruction):
        # 启用且 provider 齐全时守卫不误伤
        svc = _svc()
        audio = await svc.synthesize("你好")
        assert audio == b"RIFF....WAV"


# ================================================================== 非流式
class TestSynthesizeQwen3:
    @pytest.mark.asyncio
    async def test_routes_to_provider_and_returns_audio(self, mock_instruction):
        provider = MockProvider()
        svc = _svc(provider)
        audio = await svc.synthesize("你好，世界", ref_asset_id="ref_abc")
        assert audio == provider.audio
        kind, req = provider.requests[0]
        assert kind == "synthesize"
        assert req.text == "你好，世界"
        assert req.refs == ["ref_abc"]
        assert req.tts_instruction == "用俏皮的语气说"
        assert req.stream is False

    @pytest.mark.asyncio
    async def test_no_ref_synthesis(self, mock_instruction, isolated_store):
        provider = MockProvider()
        svc = _svc(provider)
        await svc.synthesize("无需参考音频")
        req = provider.requests[0][1]
        assert req.refs == []

    @pytest.mark.asyncio
    async def test_refs_merged_from_multiple_sources(self, mock_instruction):
        provider = MockProvider()
        svc = _svc(provider)
        await svc.synthesize("多参考", refs=["ref_a", "ref_b"], ref_asset_id="ref_c")
        req = provider.requests[0][1]
        # refs 与 ref_asset_id 合并去重
        assert req.refs == ["ref_a", "ref_b", "ref_c"]


# ================================================================== 流式
class TestSynthesizeStreamQwen3:
    @pytest.mark.asyncio
    async def test_stream_chunks_order_and_final(self, mock_instruction):
        provider = MockProvider()
        svc = _svc(provider)
        chunks = []
        async for chunk in svc.synthesize_stream("流式测试", ref_asset_id="ref_x"):
            chunks.append(chunk)
        req = provider.requests[0][1]
        assert req.stream is True
        assert req.refs == ["ref_x"]
        assert [c["chunk_index"] for c in chunks] == [0, 1]
        assert [c["audio_data"] for c in chunks] == [b"pcm1", b"pcm2"]
        assert chunks[0]["is_final"] is False
        assert chunks[1]["is_final"] is True


# ================================================================== 细粒度流式
class TestSynthesizeStreamFineQwen3:
    @pytest.mark.asyncio
    async def test_fine_stream_segments_and_final(self, mock_instruction):
        provider = MockProvider()
        svc = _svc(provider)

        async def _tokens():
            for token in ["你好", "呀，", "今天", "天气", "不错"]:
                yield token

        chunks = []
        async for chunk in svc.synthesize_stream_fine(_tokens(), char_threshold=3):
            chunks.append(chunk)

        # 至少合成了若干段音频块，且末尾有 final 标记
        assert any(c["audio_data"] for c in chunks)
        assert chunks[-1]["is_final"] is True
        # 每段都走 Qwen3 流式合成
        assert all(kind == "synthesize_stream" for kind, _ in provider.requests)


# ================================================================== 情感方法
class TestEmotionMethodsQwen3:
    @pytest.mark.asyncio
    async def test_synthesize_with_emotions_delegates(self, mock_instruction):
        provider = MockProvider()
        svc = _svc(provider)
        audio = await svc.synthesize_with_emotions("[emotion:happy]开心起来", ref_asset_id="ref_e")
        assert audio == provider.audio
        assert provider.requests[0][0] == "synthesize"

    @pytest.mark.asyncio
    async def test_synthesize_stream_with_emotions_delegates(self, mock_instruction):
        provider = MockProvider()
        svc = _svc(provider)
        chunks = []
        async for chunk in svc.synthesize_stream_with_emotions("带情绪流式", ref_asset_id="ref_e"):
            chunks.append(chunk)
        assert [c["is_final"] for c in chunks] == [False, True]
        assert provider.requests[0][0] == "synthesize_stream"


# ================================================================== 请求组装
class TestBuildRefIds:
    def test_refs_and_asset_id(self):
        svc = _svc()
        ids = svc._build_ref_ids({"refs": ["ref_a"], "ref_asset_id": "ref_b"})
        assert ids == ["ref_a", "ref_b"]

    def test_refs_string_normalized(self):
        svc = _svc()
        assert svc._build_ref_ids({"refs": "ref_single"}) == ["ref_single"]

    def test_ref_audio_asset_id_kept(self):
        svc = _svc()
        assert svc._build_ref_ids({"ref_audio": "ref_asset"}) == ["ref_asset"]

    def test_deduplicated(self):
        svc = _svc()
        ids = svc._build_ref_ids({"refs": ["ref_a", "ref_a"], "ref_asset_id": "ref_a"})
        assert ids == ["ref_a"]

    def test_empty(self, isolated_store):
        svc = _svc()
        assert svc._build_ref_ids({}) == []

    def test_falls_back_to_current_asset(self, isolated_store):
        svc = _svc()
        src = isolated_store / "cur.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        ref_audio_store.set_current(asset.id)
        assert svc._build_ref_ids({}) == [asset.id]

    def test_explicit_refs_override_current(self, isolated_store):
        svc = _svc()
        src = isolated_store / "cur.wav"
        src.write_bytes(_wav_bytes())
        asset = ref_audio_store.register_from_file(str(src))
        ref_audio_store.set_current(asset.id)
        assert svc._build_ref_ids({"refs": ["ref_x"]}) == ["ref_x"]
        assert svc._build_ref_ids({"ref_asset_id": "ref_y"}) == ["ref_y"]

    def test_no_current_returns_empty(self, isolated_store):
        svc = _svc()
        assert svc._build_ref_ids({}) == []


class TestBuildQwen3Request:
    def test_defaults_used(self, monkeypatch):
        svc = TTSService(qwen3_enabled=True, qwen3_provider=MockProvider())
        monkeypatch.setattr(svc, "_qwen3_defaults", lambda: {
            "voice": "vivian", "language": "", "output_format": "wav", "speed": 1.0
        })
        req = svc._build_qwen3_request("文本", ["ref_a"], "指令", stream=False)
        assert req.voice == "vivian"
        assert req.output_format == "wav"
        assert req.speed == 1.0
        assert req.refs == ["ref_a"]
        assert req.tts_instruction == "指令"

    def test_kwargs_override_defaults(self, monkeypatch):
        svc = TTSService(qwen3_enabled=True, qwen3_provider=MockProvider())
        monkeypatch.setattr(svc, "_qwen3_defaults", lambda: {
            "voice": "vivian", "language": "", "output_format": "wav", "speed": 1.0
        })
        req = svc._build_qwen3_request("文本", [], None, stream=True, voice="nova", speed=2.0)
        assert req.voice == "nova"
        assert req.speed == 2.0
        assert req.stream is True


# ================================================================== VoiceDesign prompt 生成器接线
class TestPromptGeneratorWiring:
    @pytest.mark.asyncio
    async def test_get_tts_service_wires_prompt_generator(self, monkeypatch):
        """get_tts_service 在 qwen3 启用时注入 VoiceDesign prompt 生成器。"""
        from server.services.tts_service import get_tts_service

        # 强制重建单例，验证接线
        monkeypatch.setattr(tts_svc_mod, "_tts_service", None)
        monkeypatch.setattr(ref_audio_store, "_prompt_generator", None)
        get_tts_service()
        gen = ref_audio_store._prompt_generator
        assert gen is not None, "get_tts_service 应注入 prompt 生成器"
        assert callable(gen)
        # 清理单例，避免影响其他测试
        monkeypatch.setattr(tts_svc_mod, "_tts_service", None)
        monkeypatch.setattr(ref_audio_store, "_prompt_generator", None)

    @pytest.mark.asyncio
    async def test_prompt_generator_routes_to_voicedesign(self, monkeypatch):
        """prompt 生成器：无 refs → VoiceDesign(vllm)，tts_instruction 承载音色描述。"""
        from server.services.tts_service import get_tts_service
        from server.qwen3_tts_provider import Qwen3TTSProvider, SynthesisResponse
        from server.ref_audio_store import GeneratedAudio

        audio_bytes = _wav_bytes()
        calls = []

        async def _fake_synth(self, req):
            calls.append(req)
            return SynthesisResponse(audio=audio_bytes, format="wav", sample_rate=24000,
                                     channels=1, duration_seconds=3.0, refs_used=[])

        # 闭包捕获真实 provider 实例，通过 patch 类方法拦截 synthesize
        monkeypatch.setattr(Qwen3TTSProvider, "synthesize", _fake_synth)
        monkeypatch.setattr(tts_svc_mod, "_tts_service", None)
        monkeypatch.setattr(ref_audio_store, "_prompt_generator", None)
        get_tts_service()
        gen = ref_audio_store._prompt_generator
        assert gen is not None

        result = await gen("温柔可爱的少女音", "Chinese")
        assert isinstance(result, GeneratedAudio)
        assert result.audio == audio_bytes
        assert result.sample_rate == 24000
        assert result.channels == 1
        # 请求无 refs、指令为音色描述
        req = calls[0]
        assert req.refs == []
        assert req.tts_instruction == "温柔可爱的少女音"
        assert req.language == "Chinese"
        assert req.output_format == "wav"
        monkeypatch.setattr(tts_svc_mod, "_tts_service", None)
        monkeypatch.setattr(ref_audio_store, "_prompt_generator", None)


# ================================================================== LLM 声音属性标签（speed/volume）结构化注入
class TestStructuredVoiceLabel:
    """LLM <tts_instruction> 结构化标签中的 speed/volume 需接入真实合成参数。

    注意：不依赖 mock_instruction fixture（它把 generate_instruction 替换为固定文本），
    而是走 emotion_instruction_service 真实解析路径。
    """

    async def _req_from(self, svc, text, **kwargs):
        """走 _synthesize_stream_fine 的核心：对单段文本生成 SynthesisRequest 并返回。"""
        instruction = await svc._gen_instruction_full(text)
        clean = tts_svc_mod.strip_instruction(text)
        seg_kwargs = tts_svc_mod._inject_label_params(kwargs, text, instruction)
        return svc._build_qwen3_request(
            clean, ["ref_a"], instruction.text if instruction else None,
            stream=True, **seg_kwargs
        )

    @pytest.mark.asyncio
    async def test_json_label_injects_speed_and_volume(self):
        svc = TTSService(qwen3_enabled=True, qwen3_provider=MockProvider(),
                         emotion_instruction_enabled=True)
        text = '正文<tts_instruction>{"text":"轻声说","speed":0.7,"volume":0.4}</tts_instruction>'
        req = await self._req_from(svc, text)
        assert req.speed == 0.7
        assert req.volume == 0.4
        assert req.tts_instruction == "轻声说"
        assert req.text == "正文"

    @pytest.mark.asyncio
    async def test_pure_text_label_keeps_defaults(self):
        svc = TTSService(qwen3_enabled=True, qwen3_provider=MockProvider(),
                         emotion_instruction_enabled=True)
        text = '太棒了！<tts_instruction>用开心语气说</tts_instruction>'
        req = await self._req_from(svc, text)
        assert req.speed == 1.0  # 纯文本标签无 speed → 保持默认
        assert req.volume == 1.0

    @pytest.mark.asyncio
    async def test_json_label_only_speed(self):
        svc = TTSService(qwen3_enabled=True, qwen3_provider=MockProvider(),
                         emotion_instruction_enabled=True)
        text = '快一点<tts_instruction>{"text":"快速说","speed":1.6}</tts_instruction>'
        req = await self._req_from(svc, text)
        assert req.speed == 1.6
        assert req.volume == 1.0  # 未显式指定 volume → 保持默认

    @pytest.mark.asyncio
    async def test_label_overrides_config_speed_but_keeps_volume_default(self, monkeypatch):
        """标签显式指定 speed 覆盖 config 默认；未指定 volume 不引入、保持默认。"""
        svc = TTSService(qwen3_enabled=True, qwen3_provider=MockProvider(),
                         emotion_instruction_enabled=True)
        monkeypatch.setattr(svc, "_qwen3_defaults", lambda: {
            "voice": "vivian", "language": "", "output_format": "wav", "speed": 2.0
        })
        text = '轻声<tts_instruction>{"text":"小声说","speed":0.5}</tts_instruction>'
        req = await self._req_from(svc, text, speed=2.0)
        # 标签显式指定 speed=0.5 → 覆盖 config 默认
        assert req.speed == 0.5
        # 标签未指定 volume → 不引入 volume，保持默认 1.0
        assert req.volume == 1.0