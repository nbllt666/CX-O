"""统一 Qwen3 TTS Provider (server/qwen3_tts_provider.py) 单元测试。

Task 2 [P] 闭合判据：Provider 单测与 Mock 合成覆盖成功、超时、断流、非法响应、
双来源 refs 与取消。用 Fake/Mock 客户端模拟 vLLM/官方运行时响应，不依赖真实运行时。

覆盖：
- 非流式 synthesize：成功、超时、连接失败、HTTP 状态映射、空/非法响应
- 流式 synthesize_stream：chunk 边界（恰一 start/一 final）、断流、取消(StreamAbortedError)
- 请求校验：非法 text/format/speed、情感指令超长、refs 前缀校验
- 参考音频：ref_resolver 未接入(RefAudioNotFoundError)、采样率越界、
  双来源 refs 重采样到 24kHz 并进入请求体
- 运行时：vLLM 首选、speed 能力官方运行时兜底、未配置兜底时 RuntimeUnsupportedError
- health_check 轻量探活、close 资源清理、旧引擎检测(LegacyEngineRemovedError)

运行：python -m pytest tests/test_qwen3_tts_provider.py -q
"""
import array
import asyncio
import base64

import httpx
import pytest

from server.qwen3_tts_provider import (
    AudioChunk,
    InvalidRefAudioError,
    InvalidRequestError,
    LegacyEngineRemovedError,
    Qwen3TTSProvider,
    RefAudioNotFoundError,
    ResolvedRef,
    RuntimeUnavailableError,
    RuntimeUnsupportedError,
    StreamAbortedError,
    SynthesisRequest,
    EmotionInstructionInvalidError,
    detect_legacy_engine,
    detect_legacy_engine_mode,
)

SYNTH_SAMPLE_RATE = 24000


# ============================================================================
# Fake/Mock 客户端
# ============================================================================
class FakeResponse:
    """最小 httpx.Response 替身：供 post/get 使用。"""

    def __init__(self, content: bytes = b"", status_code: int = 200):
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://fake"),
                response=httpx.Response(self.status_code, request=httpx.Request("POST", "http://fake")),
            )


class FakeStreamResp:
    """流式响应替身：支持 raise_for_status 与 aiter_bytes。"""

    def __init__(self, chunks, status_code: int = 200, error: Exception | None = None):
        # chunks 可为同步可迭代(list/tuple)或异步可迭代(async generator)
        self._chunks = chunks
        self.status_code = status_code
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://fake"),
                response=httpx.Response(self.status_code, request=httpx.Request("POST", "http://fake")),
            )

    async def aiter_bytes(self):
        if hasattr(self._chunks, "__aiter__"):
            async for c in self._chunks:
                yield c
        else:
            for c in self._chunks:
                yield c


class FakeStreamCtx:
    """async 上下文管理器替身，供 client.stream() 使用。"""

    def __init__(self, resp: FakeStreamResp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class FakeClient:
    """httpx.AsyncClient 替身：可配置 post/get/stream 的行为并捕获请求体。"""

    def __init__(
        self,
        post_response: FakeResponse | None = None,
        post_error: Exception | None = None,
        get_response: FakeResponse | None = None,
        get_error: Exception | None = None,
        stream_resp: FakeStreamResp | None = None,
    ):
        self.post_response = post_response or FakeResponse()
        self.post_error = post_error
        self.get_response = get_response or FakeResponse()
        self.get_error = get_error
        self.stream_resp = stream_resp
        self.last_json = None
        self.last_url = None
        self.closed = False

    async def post(self, url, json=None, timeout=None):
        self.last_url = url
        self.last_json = json
        if self.post_error:
            raise self.post_error
        return self.post_response

    async def get(self, url, timeout=None):
        self.last_url = url
        if self.get_error:
            raise self.get_error
        return self.get_response

    def stream(self, method, url, json=None, timeout=None):
        self.last_url = url
        self.last_json = json
        return FakeStreamCtx(self.stream_resp or FakeStreamResp([]))

    async def aclose(self):
        self.closed = True


def _pcm16(nsamples: int, fill: int = 100) -> bytes:
    """构造 16-bit signed LE mono PCM 数据。"""
    a = array.array("h", [fill] * nsamples)
    return a.tobytes()


def _cfg(official_base_url: str = "", runtime: str = "vllm") -> dict:
    """构造 Provider 配置 dict（直接注入，避免依赖真实 settings）。"""
    return {
        "enabled": True,
        "runtime": runtime,
        "vllm": {
            "base_url": "http://127.0.0.1:8091",
            "model": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            "task_type": "CustomVoice",
            "timeout_seconds": 60,
            "sample_rate": 24000,
        },
        "official_runtime": {
            "base_url": official_base_url,
            "model": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
            "timeout_seconds": 60,
        },
        "default": {"voice": "vivian", "language": "", "output_format": "wav", "speed": 1.0},
        "emotion_instruction": {"enabled": True, "max_length": 200, "fallback_neutral": True},
        "legacy_engine_removed": {"return_removed_error": True},
    }


def _make_client(**kw) -> FakeClient:
    return FakeClient(**kw)


def _req(**kw) -> SynthesisRequest:
    defaults = dict(text="你好", refs=[], tts_instruction=None, voice=None,
                    language=None, stream=False, output_format="pcm", speed=1.0)
    defaults.update(kw)
    return SynthesisRequest(**defaults)


# ============================================================================
# 非流式 synthesize
# ============================================================================
class TestSynthesize:
    @pytest.mark.asyncio
    async def test_success(self):
        audio = _pcm16(4800)
        client = _make_client(post_response=FakeResponse(content=audio))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        resp = await p.synthesize(_req())
        assert resp.audio == audio
        assert resp.format == "pcm"
        assert resp.sample_rate == SYNTH_SAMPLE_RATE
        assert resp.channels == 1
        assert resp.runtime == "vllm"
        assert "v1/audio/speech" in client.last_url
        assert client.last_json["task_type"] == "CustomVoice"  # vLLM 私有参数入口

    @pytest.mark.asyncio
    async def test_timeout_raises_unavailable(self):
        client = _make_client(post_error=httpx.TimeoutException("timeout"))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(RuntimeUnavailableError):
            await p.synthesize(_req())

    @pytest.mark.asyncio
    async def test_connect_error_raises_unavailable(self):
        client = _make_client(post_error=httpx.ConnectError("conn refused"))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(RuntimeUnavailableError):
            await p.synthesize(_req())

    @pytest.mark.asyncio
    async def test_http_400_maps_invalid_request(self):
        client = _make_client(post_response=FakeResponse(content=b"", status_code=400))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(InvalidRequestError):
            await p.synthesize(_req())

    @pytest.mark.asyncio
    async def test_http_404_maps_ref_not_found(self):
        client = _make_client(post_response=FakeResponse(content=b"", status_code=404))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(RefAudioNotFoundError):
            await p.synthesize(_req())

    @pytest.mark.asyncio
    async def test_http_422_maps_invalid_ref(self):
        client = _make_client(post_response=FakeResponse(content=b"", status_code=422))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(InvalidRefAudioError):
            await p.synthesize(_req())

    @pytest.mark.asyncio
    async def test_http_503_maps_runtime_unavailable(self):
        client = _make_client(post_response=FakeResponse(content=b"", status_code=503))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(RuntimeUnavailableError):
            await p.synthesize(_req())

    @pytest.mark.asyncio
    async def test_empty_audio_invalid_response(self):
        client = _make_client(post_response=FakeResponse(content=b""))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(RuntimeUnavailableError):
            await p.synthesize(_req())


# ============================================================================
# 流式 synthesize_stream
# ============================================================================
class TestSynthesizeStream:
    @pytest.mark.asyncio
    async def test_success_chunk_boundaries(self):
        chunks = [_pcm16(240), _pcm16(240), _pcm16(240)]
        client = _make_client(stream_resp=FakeStreamResp(chunks))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        got: list[AudioChunk] = [c async for c in p.synthesize_stream(_req())]
        assert len(got) == 3
        assert sum(1 for c in got if c.is_start) == 1
        assert sum(1 for c in got if c.is_final) == 1
        assert got[0].is_start is True
        assert got[-1].is_final is True
        assert [c.index for c in got] == [0, 1, 2]
        assert got[0].sample_rate == SYNTH_SAMPLE_RATE

    @pytest.mark.asyncio
    async def test_wav_header_skipped(self):
        # 44 字节 WAV 头：首块 100 字节 = 44 头 + 56 数据
        chunks = [b"\x00" * 100, _pcm16(240)]
        client = _make_client(stream_resp=FakeStreamResp(chunks))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        got = [c async for c in p.synthesize_stream(_req(output_format="wav"))]
        assert got[0].data == b"\x00" * 56  # 头部被跳过
        assert got[0].format == "wav"

    @pytest.mark.asyncio
    async def test_broken_stream_raises_unavailable(self):
        chunks = [_pcm16(240)]
        stream = FakeStreamResp(chunks, error=httpx.ReadError("connection reset"))
        client = _make_client(stream_resp=stream)
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(RuntimeUnavailableError):
            async for _ in p.synthesize_stream(_req()):
                pass

    @pytest.mark.asyncio
    async def test_empty_stream_raises_unavailable(self):
        client = _make_client(stream_resp=FakeStreamResp([]))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        with pytest.raises(RuntimeUnavailableError):
            async for _ in p.synthesize_stream(_req()):
                pass

    @pytest.mark.asyncio
    async def test_cancel_raises_stream_aborted(self):
        async def infinite_stream():
            # 持续产出 chunk，直到被取消
            while True:
                yield _pcm16(240)
                await asyncio.sleep(0.001)

        client = _make_client(stream_resp=FakeStreamResp(infinite_stream()))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)

        async def consume():
            async for _ in p.synthesize_stream(_req()):
                pass

        task = asyncio.ensure_future(consume())
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(StreamAbortedError):
            await task


# ============================================================================
# 请求校验
# ============================================================================
class TestRequestValidation:
    def test_empty_text_invalid(self):
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client())
        with pytest.raises(InvalidRequestError):
            p._validate_request(_req(text="   "))

    def test_bad_format_invalid(self):
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client())
        with pytest.raises(InvalidRequestError):
            p._validate_request(_req(output_format="ogg"))

    def test_speed_out_of_range_invalid(self):
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client())
        with pytest.raises(InvalidRequestError):
            p._validate_request(_req(speed=9.0))

    def test_refs_require_prefix(self):
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client())
        with pytest.raises(InvalidRequestError):
            p._validate_request(_req(refs=["/etc/passwd"]))

    def test_emotion_instruction_too_long(self):
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client())
        with pytest.raises(EmotionInstructionInvalidError):
            p._validate_request(_req(tts_instruction="啊" * 300))


# ============================================================================
# 参考音频
# ============================================================================
class TestRefs:
    @pytest.mark.asyncio
    async def test_resolver_not_attached(self):
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client(), ref_resolver=None)
        with pytest.raises(RefAudioNotFoundError):
            await p.synthesize(_req(refs=["ref_voice_a"]))

    @pytest.mark.asyncio
    async def test_resolver_returns_none(self):
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client(), ref_resolver=lambda aid: None)
        with pytest.raises(RefAudioNotFoundError):
            await p.synthesize(_req(refs=["ref_voice_a"]))

    @pytest.mark.asyncio
    async def test_sample_rate_out_of_range(self):
        bundle = ResolvedRef(asset_id="ref_a", data=_pcm16(48), sample_rate=6000)
        p = Qwen3TTSProvider(config=_cfg(), http_client=_make_client(), ref_resolver=lambda aid: bundle)
        with pytest.raises(InvalidRefAudioError):
            await p.synthesize(_req(refs=["ref_a"]))

    @pytest.mark.asyncio
    async def test_dual_source_refs_resampled_to_24k(self):
        # 双来源：a 为 48kHz，b 为 8kHz，均重采样到 24kHz 并进入请求体
        resolver = {
            "ref_prompt": ResolvedRef(asset_id="ref_prompt", data=_pcm16(480), sample_rate=48000, ref_text="p"),
            "ref_file": ResolvedRef(asset_id="ref_file", data=_pcm16(80), sample_rate=8000, ref_text="f"),
        }
        client = _make_client(post_response=FakeResponse(content=_pcm16(240)))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client, ref_resolver=lambda aid: resolver[aid])
        resp = await p.synthesize(_req(refs=["ref_prompt", "ref_file"]))
        assert resp.refs_used == ["ref_prompt", "ref_file"]
        body = client.last_json
        # 48kHz 480 样本 -> 24kHz 240 样本；8kHz 80 样本 -> 24kHz 240 样本
        assert len(base64.b64decode(body["ref_audio"][0])) == 240 * 2
        assert len(base64.b64decode(body["ref_audio"][1])) == 240 * 2
        assert body["ref_text"] == ["p", "f"]


# ============================================================================
# 运行时选择
# ============================================================================
class TestRuntimeSelection:
    @pytest.mark.asyncio
    async def test_speed_control_falls_back_to_official(self):
        client = _make_client(post_response=FakeResponse(content=_pcm16(240)))
        p = Qwen3TTSProvider(config=_cfg(official_base_url="http://127.0.0.1:8092"), http_client=client)
        req = _req(speed=1.5)
        resp = await p.synthesize(req)
        assert resp.runtime == "official_qwen3"
        assert "8092" in client.last_url

    @pytest.mark.asyncio
    async def test_speed_control_no_official_raises_unsupported(self):
        client = _make_client(post_response=FakeResponse(content=_pcm16(240)))
        p = Qwen3TTSProvider(config=_cfg(official_base_url=""), http_client=client)
        with pytest.raises(RuntimeUnsupportedError):
            await p.synthesize(_req(speed=1.5))


# ============================================================================
# 健康检查 / 关闭 / 旧引擎
# ============================================================================
class TestHealthCloseLegacy:
    @pytest.mark.asyncio
    async def test_health_ok(self):
        client = _make_client(get_response=FakeResponse(content=b"ok", status_code=200))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        h = await p.health_check()
        assert h.ok is True
        assert h.runtime == "vllm"
        assert h.latency_ms is not None

    @pytest.mark.asyncio
    async def test_health_unreachable(self):
        client = _make_client(get_error=httpx.ConnectError("down"))
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        h = await p.health_check()
        assert h.ok is False
        assert h.runtime == "vllm"

    @pytest.mark.asyncio
    async def test_close_does_not_close_shared_client(self):
        client = _make_client()
        p = Qwen3TTSProvider(config=_cfg(), http_client=client)
        await p.close()
        assert client.closed is False  # 共享客户端交给生命周期管理

    def test_detect_legacy_engine_raises(self):
        with pytest.raises(LegacyEngineRemovedError):
            detect_legacy_engine({"orpheus": {"url": "x"}})

    def test_detect_legacy_engine_mode_raises(self):
        with pytest.raises(LegacyEngineRemovedError):
            detect_legacy_engine_mode("f5-tts")