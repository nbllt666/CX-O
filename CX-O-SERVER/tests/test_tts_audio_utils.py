"""
server/services/tts_audio_utils.py 回归测试
TTS 纯工具函数：静音检测/跨请求静音过滤/分句/静音生成/音频拼接
"""
import struct

import pytest

from server.services.tts_audio_utils import (
    CrossRequestSilenceFilter,
    concatenate_audio,
    generate_silence,
    is_silence_pcm,
    split_text_by_sentences,
)

FRAME_SIZE = 960  # 480 samples * 2 bytes


def _pcm_samples(amplitude: int, n: int = 480) -> bytes:
    return struct.pack(f"<{n}h", *([amplitude] * n))


NUMPY = True
try:
    import numpy  # noqa: F401
except ImportError:
    NUMPY = False


class TestIsSilencePcm:
    def test_silence_zeros(self):
        assert is_silence_pcm(_pcm_samples(0)) is True

    def test_quiet_below_threshold(self):
        assert is_silence_pcm(_pcm_samples(100)) is True

    def test_loud_above_threshold(self):
        assert is_silence_pcm(_pcm_samples(1000), threshold=500) is False

    def test_short_bytes_returns_true(self):
        assert is_silence_pcm(b"\x00\x00") is True

    def test_empty_returns_true(self):
        assert is_silence_pcm(b"") is True


class TestSplitTextBySentences:
    def test_chinese_sentences_merged_under_max(self):
        # 短文本（< max_length）会合并为单个 chunk
        parts = split_text_by_sentences("你好。世界！", max_length=200)
        assert parts == ["你好。世界！"]

    def test_long_text_splits_by_max_length(self):
        # 超过 max_length 时按句切分
        long_sentence = "句" * 150
        parts = split_text_by_sentences(long_sentence, max_length=200)
        assert len(parts) >= 1
        assert all(len(p) <= 200 for p in parts)

    def test_merge_to_max_length(self):
        text = "。" .join(["句子" * 30] * 5)
        parts = split_text_by_sentences(text, max_length=200)
        assert len(parts) >= 2
        assert all(len(p) <= 200 for p in parts)

    def test_no_punctuation_single_part(self):
        parts = split_text_by_sentences("没有标点的长文本", max_length=200)
        assert parts == ["没有标点的长文本"]

    def test_empty_text(self):
        assert split_text_by_sentences("") == []


class TestGenerateSilence:
    def test_returns_wav_bytes(self):
        wav = generate_silence(100)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert len(wav) > 44

    def test_duration_affects_size(self):
        wav_short = generate_silence(10)
        wav_long = generate_silence(200)
        assert len(wav_long) > len(wav_short)


class TestConcatenateAudio:
    def test_empty_returns_empty(self):
        import asyncio
        assert asyncio.run(concatenate_audio([])) == b""

    def test_single_segment_returns_as_is(self):
        import asyncio
        assert asyncio.run(concatenate_audio([b"abc"])) == b"abc"

    def test_wav_concatenation(self):
        import asyncio
        wav_a = generate_silence(100)
        wav_b = generate_silence(100)
        result = asyncio.run(concatenate_audio([wav_a, wav_b]))
        assert result[:4] == b"RIFF"
        chunk_wav = generate_silence(100)
        orig_data_size = chunk_wav[40:44]
        assert len(result) > len(wav_a)  # 拼接后更长

    def test_non_wav_concatenation(self):
        import asyncio
        result = asyncio.run(concatenate_audio([b"aaa", b"bbb"]))
        assert result == b"aaabbb"


@pytest.mark.skipif(not NUMPY, reason="numpy 未安装")
class TestCrossRequestSilenceFilter:
    def test_silent_frames_kept_until_threshold(self):
        f = CrossRequestSilenceFilter(max_silence_frames=3, frame_size=FRAME_SIZE)
        out = f.feed(_pcm_samples(0, n=FRAME_SIZE // 2) * 3)
        assert len(out) == FRAME_SIZE * 3  # 前 3 帧保留

    def test_long_silence_skipped(self):
        f = CrossRequestSilenceFilter(max_silence_frames=2, frame_size=FRAME_SIZE)
        out = f.feed(_pcm_samples(0, n=FRAME_SIZE // 2) * 5)
        # 5 帧静音，前 2 帧保留，后 3 帧跳过
        assert len(out) == FRAME_SIZE * 2

    def test_non_silence_resets_counter(self):
        f = CrossRequestSilenceFilter(max_silence_frames=2, frame_size=FRAME_SIZE)
        out = f.feed(_pcm_samples(0, n=FRAME_SIZE // 2) * 3 + _pcm_samples(2000, n=FRAME_SIZE // 2))
        # 3 静音(保留2跳过1) + 1 非静音(重置)
        assert len(out) == FRAME_SIZE * 2 + FRAME_SIZE

    def test_flush_returns_remainder(self):
        f = CrossRequestSilenceFilter(frame_size=FRAME_SIZE)
        # 不足一帧的尾部数据
        f.feed(b"\x00" * 100)
        assert len(f.flush()) == 100
        assert len(f.flush()) == 0  # 二次 flush 为空

    def test_stats(self):
        f = CrossRequestSilenceFilter(max_silence_frames=1, frame_size=FRAME_SIZE)
        f.feed(_pcm_samples(0, n=FRAME_SIZE // 2) * 3)
        stats = f.get_stats()
        assert stats["total_frames"] == 3
        assert stats["silence_skipped"] == 2
        assert stats["silence_ratio"] == pytest.approx(2 / 3)
