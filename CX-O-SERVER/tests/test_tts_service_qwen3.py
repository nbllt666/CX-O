"""TTSService 统一 Qwen3 编排 Mock E2E 测试。

Task 5 闭合判据：后端普通/实时/直播链路定向测试与 Qwen3 Mock E2E 通过。

用 MockProvider 注入 Qwen3 Provider + monkeypatch 情感指令生成，验证统一编排入口
在 qwen3_enabled 时优先走 Qwen3，覆盖：

- 非流式 synthesize：剥离指令、生成指令、refs 归一化、委托 Provider、返回音频
- 无参考音频合成（refs 为空列表）
- 流式 synthesize_stream：chunk 顺序与 is_final 保持
- 细粒度流式 synthesize_stream_fine：token 流分块 → 逐段合成 → 末尾 final
- 情感方法 synthesize_with_emotions / synthesize_stream_with_emotions 委托 Qwen3
- _build_ref_ids 五来源归一化（refs / ref_asset_id / ref_audio 资产ID / base64 / path）
- _build_qwen3_request defaults 读取与 kwargs 覆盖
- 向后兼容：qwen3_enabled=False 时回退旧链路（orpheus 模式）

运行：python -m pytest tests/test_tts_service_qwen3.py -q
"""
import io
import wave

import pytest

from server import ref_audio_store
from server.services import tts_service as tts_svc_mod
from server.services.tts_service import TTSService
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
    async def test_no_ref_synthesis(self, mock_instruction):
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

    @pytest.mark.asyncio
    async def test_qwen3_disabled_falls_through(self, mock_instruction):
        """向后兼容：qwen3_enabled=False 时不走 Provider，回退旧链路。"""
        provider = MockProvider()
        svc = TTSService(
            qwen3_enabled=False, qwen3_provider=provider,
            mode="orpheus", orpheus_url="http://127.0.0.1:1",
        )
        # mode=orpheus 会尝试 HTTP 调用，此处用 monkeypatch 拦截 _synthesize_orpheus
        async def _fake_orpheus(text, voice=None, **kw):
            return b"orpheus-audio"
        svc._synthesize_orpheus = _fake_orpheus
        audio = await svc.synthesize("旧引擎")
        assert audio == b"orpheus-audio"
        assert provider.requests == []  # 未走 Qwen3


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

    def test_empty(self):
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