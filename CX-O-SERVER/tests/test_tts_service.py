"""server.services.tts_service (TTSService) 单元测试。

聚焦可隔离测试的纯逻辑与内部辅助方法，隔离网络（httpx/retry）与 F5-TTS 模型：

- _build_tts_request_data：请求 payload 构造与类型强转
- _validate_triton_for_low_latency：低延迟模型 Triton 自动启用
- get_emotion_voice / _resolve_audio_path / _load_emotion_voices：音色与参考音频解析
- split_text_streaming：细粒度流式分块（字数阈值 + 停顿标点双触发）
- _load_ref_audio / _load_emotion_audio：参考音频加载与缓存

运行：python -m pytest tests/test_tts_service.py -v
"""
import types

import pytest

from server.services.tts_service import TTSService, _load_emotion_voices


def _svc(**kw):
    return TTSService(**kw)


# ================================================================ _build_tts_request_data
class TestBuildRequestData:
    def test_defaults(self):
        files, data = _svc()._build_tts_request_data("hi", "ref", b"\x00\x01")
        assert files["ref_audio"][2] == "audio/wav"
        assert data["gen_text"] == "hi"
        assert data["model_type"] == "F5-TTS"
        assert data["speed"] == "1.0"
        assert data["nfe_step"] == "32"
        assert data["cfg_strength"] == "2"
        assert data["remove_silence"] == "false"  # bool → 小写字符串

    def test_custom_kwargs(self):
        _, data = _svc()._build_tts_request_data(
            "hi", "ref", b"x", speed=1.5, model_type="Qwen3-TTS", nfe_step=64
        )
        assert data["speed"] == "1.5"
        assert data["model_type"] == "Qwen3-TTS"
        assert data["nfe_step"] == "64"


# ================================================================ Triton 校验
class TestValidateTriton:
    @pytest.mark.asyncio
    async def test_low_latency_auto_enables_with_gateway(self):
        s = _svc(use_triton=False, gateway_url="http://gw:8000/")
        await s._validate_triton_for_low_latency(model_type="Qwen3-TTS")
        assert s._use_triton is True

    @pytest.mark.asyncio
    async def test_low_latency_no_gateway_keeps_disabled(self):
        s = _svc(use_triton=False, gateway_url=None)
        await s._validate_triton_for_low_latency(model_type="qwen3-tts")
        assert s._use_triton is False

    @pytest.mark.asyncio
    async def test_non_low_latency_unchanged(self):
        s = _svc(use_triton=False, gateway_url="http://gw")
        await s._validate_triton_for_low_latency(model_type="F5-TTS")
        assert s._use_triton is False

    @pytest.mark.asyncio
    async def test_already_triton_unchanged(self):
        s = _svc(use_triton=True, gateway_url="http://gw")
        await s._validate_triton_for_low_latency(model_type="Qwen3-TTS")
        assert s._use_triton is True


# ================================================================ 音色解析
class TestEmotionVoice:
    def test_get_emotion_voice_specific(self):
        s = _svc(emotion_voices={"happy": {"ref_audio": "a.wav"}})
        assert s.get_emotion_voice("happy")["ref_audio"] == "a.wav"

    def test_get_emotion_voice_fallback_normal(self):
        s = _svc(emotion_voices={"normal": {"ref_audio": "n.wav"}})
        assert s.get_emotion_voice("sad")["ref_audio"] == "n.wav"

    def test_get_emotion_voice_fallback_neutral(self):
        # canonical "neutral" 音色键（VoiceWorkStation 产出契约）可作中性回退，
        # 修复前仅认历史 "normal"，[emotion:neutral] 无法命中生成的中性音色。
        s = _svc(emotion_voices={"neutral": {"ref_audio": "nu.wav"}})
        assert s.get_emotion_voice("sad")["ref_audio"] == "nu.wav"
        assert s.get_emotion_voice("fear")["ref_audio"] == "nu.wav"

    def test_get_emotion_voice_neutral_preferred_over_normal(self):
        s = _svc(emotion_voices={
            "neutral": {"ref_audio": "nu.wav"},
            "normal": {"ref_audio": "no.wav"},
        })
        assert s.get_emotion_voice("sad")["ref_audio"] == "nu.wav"

    def test_get_emotion_voice_default(self):
        s = _svc(ref_audio_path="d.wav", ref_text="rt")
        v = s.get_emotion_voice("sad")
        assert v["ref_audio"] == "d.wav"
        assert v["ref_text"] == "rt"


class TestResolveAudioPath:
    def test_empty_returns_none(self, tmp_path):
        assert _svc()._resolve_audio_path("") is None

    def test_absolute_path(self, tmp_path):
        p = tmp_path / "a.wav"
        p.write_bytes(b"x")
        assert _svc()._resolve_audio_path(str(p)) == p

    def test_voice_refs_dir(self, tmp_path):
        refs = tmp_path / "refs"
        refs.mkdir()
        (refs / "tara.wav").write_bytes(b"x")
        s = _svc(voice_refs_dir=str(refs))
        resolved = s._resolve_audio_path("tara.wav")
        assert resolved == refs / "tara.wav"

    def test_missing_returns_none(self, tmp_path):
        assert _svc()._resolve_audio_path("nope.wav") is None


class TestLoadEmotionVoices:
    """回归：_load_emotion_voices 收敛到 tts_audio_utils.load_emotion_voices。

    修正前 tts_service 内扁平扫描（遍历目录下散落 wav）与 VoiceWorkStation
    产出布局（{emotion}/ref.wav + ref.txt 子目录 / emotion_mapping.json）不兼容，
    实际加载不到任何音色。本类验证子目录布局可被正确发现。
    """

    def test_mapping_file_used(self, tmp_path):
        import json

        (tmp_path / "emotion_mapping.json").write_text(
            json.dumps({"happy": {"ref_audio": "a.wav", "ref_text": "haha"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        result = _load_emotion_voices(str(tmp_path))
        assert result["happy"]["ref_audio"] == "a.wav"
        assert result["happy"]["ref_text"] == "haha"

    def test_subdir_layout_discovered(self, tmp_path):
        happy = tmp_path / "happy"
        happy.mkdir(parents=True)
        (happy / "ref.wav").write_bytes(b"WAV")
        (happy / "ref.txt").write_text("开开心心", encoding="utf-8")
        result = _load_emotion_voices(str(tmp_path))
        assert "happy" in result
        assert result["happy"]["ref_audio"].endswith("ref.wav")
        assert result["happy"]["ref_text"] == "开开心心"

    def test_empty_dir(self, tmp_path):
        assert _load_emotion_voices(str(tmp_path)) == {}

    def test_none_path(self):
        assert _load_emotion_voices(None) == {}


# ================================================================ 参考音频加载
class TestLoadRefAudio:
    @pytest.mark.asyncio
    async def test_no_path_raises(self):
        with pytest.raises(ValueError):
            await _svc()._load_ref_audio()

    @pytest.mark.asyncio
    async def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ValueError):
            await _svc(ref_audio_path=str(tmp_path / "no.wav"))._load_ref_audio()

    @pytest.mark.asyncio
    async def test_loads_and_caches(self, tmp_path):
        p = tmp_path / "ref.wav"
        p.write_bytes(b"\x00\x01")
        s = _svc(ref_audio_path=str(p))
        audio = await s._load_ref_audio()
        assert audio == b"\x00\x01"
        # 二次调用命中缓存
        s._ref_audio_path = str(tmp_path / "other.wav")  # 若未缓存会因文件缺失报错
        assert await s._load_ref_audio() == b"\x00\x01"


class TestLoadEmotionAudio:
    @pytest.mark.asyncio
    async def test_falls_back_to_ref_audio(self, tmp_path):
        p = tmp_path / "ref.wav"
        p.write_bytes(b"DATA")
        s = _svc(ref_audio_path=str(p))
        audio = await s._load_emotion_audio("happy")
        assert audio == b"DATA"

    @pytest.mark.asyncio
    async def test_loads_specific_voice(self, tmp_path):
        p = tmp_path / "ref.wav"
        p.write_bytes(b"DATA")
        s = _svc(
            ref_audio_path=str(p),
            emotion_voices={"happy": {"ref_audio": str(p)}},
        )
        # 特定情感无独立文件时回退 ref_audio
        assert await s._load_emotion_audio("happy") == b"DATA"


# ================================================================ split_text_streaming
class TestSplitTextStreaming:
    async def _collect(self, s, tokens, threshold=3):
        async def gen():
            for t in tokens:
                yield t
        return [chunk async for chunk in s.split_text_streaming(gen(), char_threshold=threshold)]

    @pytest.mark.asyncio
    async def test_splits_on_character_threshold(self):
        s = _svc()
        # 逐字喂入：每达 3 个中文字符切一次，剩余 flush
        chunks = await self._collect(s, list("你好世界大家"), threshold=3)
        assert chunks == ["你好世", "界大家"]

    @pytest.mark.asyncio
    async def test_splits_on_pause_punctuation(self):
        s = _svc()
        # 遇逗号即切片（保留逗号）
        chunks = await self._collect(s, list("你好，世界"), threshold=100)
        assert chunks == ["你好，", "世界"]

    @pytest.mark.asyncio
    async def test_threshold_clamped(self):
        s = _svc()
        # char_threshold 被 clamp 到 2~5；逐字喂入 6 个英文不计数 → 整段 flush
        chunks = await self._collect(s, list("abcdef"), threshold=99)
        assert chunks == ["abcdef"]

    @pytest.mark.asyncio
    async def test_empty_tokens(self):
        s = _svc()
        assert await self._collect(s, []) == []

    @pytest.mark.asyncio
    async def test_non_chinese_not_counted(self):
        s = _svc()
        # 英文不计入中文字数，3 个中文达阈值后切片
        chunks = await self._collect(s, list("ab好好好"), threshold=3)
        # "ab好" + "好好" ？逐字：ab 不计数，好1 好2 好3 达阈值 → 切 "ab好好好"
        assert chunks == ["ab好好好"]

    @pytest.mark.asyncio
    async def test_whitespace_flushed(self):
        s = _svc()
        chunks = await self._collect(s, ["  "])
        assert chunks == []  # 全空白不产出


# ================================================================ 流式情感+音效合成
class TestSynthesizeStreamWithEmotions:
    """回归：效果分支必须用 EffectParser 产出的 type="effect" 匹配。

    修正前循环误判 type == "sound"（EffectParser 从不产出该类型），导致
    [effect:xxx] 音效段被静默跳过，音效 chunk 永不生成。本类验证修复。
    """

    async def _collect(self, s, text):
        chunks = []
        async for chunk in s.synthesize_stream_with_emotions(text):
            chunks.append(chunk)
        return chunks

    @pytest.mark.asyncio
    async def test_effect_marker_yields_effect_chunk(self, tmp_path):
        p = tmp_path / "ref.wav"
        p.write_bytes(b"DATA")
        s = _svc(ref_audio_path=str(p), ref_text="rt")
        # 文本段走 TTS 请求（mock），音效段走 _load_effect_audio（mock）
        import unittest.mock as mock

        s._make_tts_request = mock.AsyncMock(return_value=b"TTS")
        s._load_effect_audio = mock.Mock(return_value=b"EFF")

        chunks = await self._collect(s, "[effect:door]你好")

        effect_chunks = [c for c in chunks if c.get("is_effect")]
        assert effect_chunks, "音效段应产出 is_effect 的 chunk"
        assert effect_chunks[0]["effect_name"] == "door"
        assert effect_chunks[0]["audio_data"] == b"EFF"

    @pytest.mark.asyncio
    async def test_emotion_and_effect_mixed(self, tmp_path):
        p = tmp_path / "ref.wav"
        p.write_bytes(b"DATA")
        s = _svc(ref_audio_path=str(p), ref_text="rt")
        import unittest.mock as mock

        s._make_tts_request = mock.AsyncMock(return_value=b"TTS")
        s._load_effect_audio = mock.Mock(return_value=b"EFF")

        chunks = await self._collect(s, "[emotion:happy]太棒了[effect:laugh]哈哈哈")

        assert any(c.get("is_effect") and c["effect_name"] == "laugh" for c in chunks)
        # 文本段携带正确情感
        text_chunks = [c for c in chunks if c.get("is_effect") is False and c.get("is_sleep") is not True]
        assert text_chunks and all(c.get("emotion") == "happy" for c in text_chunks)


# ================================================================ 其他
class TestMisc:
    @pytest.mark.asyncio
    async def test_get_voices(self):
        assert await _svc().get_voices() == [{"id": "default", "name": "Default Voice"}]

    @pytest.mark.asyncio
    async def test_initialize_remote(self):
        s = _svc(mode="remote")
        await s.initialize()
        assert s._initialized is True

    def test_mode_property(self):
        assert _svc(mode="orpheus").mode == "orpheus"
