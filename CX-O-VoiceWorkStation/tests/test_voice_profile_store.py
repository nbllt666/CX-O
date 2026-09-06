"""voice_profile_store 单测（change-id: enhance-cover-pitch-analysis-duet SubTask 2.3）

覆盖：
- 空数据源 / 非法 speaker 名 → None（不抛错，冻结契约 None 语义）
- 合成 440Hz wav → 真实画像断言（median MIDI≈69）+ 缓存落盘 + 全键结构
- 缓存命中：MD5 不变二次调用不重算（计数器断言）
- 缓存失效：文件 mtime 变化 → MD5 变化 → 重算
- 抽样上限：wav 数超 _MAX_ANALYZE_FILES 时均匀抽样（sample_count=上限）
- list_profiles：只含有画像的 speaker、按名称升序、含 dataset_md5/computed_at
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from workstation.config import get_settings
from workstation.services import voice_profile_store as store
from workstation.services.vocal_analysis import (
    VoiceAnalysisError,
    VoiceProfile,
)


@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    """隔离画像环境：训练数据与缓存目录均指向 tmp_path（不污染真实数据源）。"""
    settings = get_settings()
    training_dir = tmp_path / "training" / "sovits_svc"
    raw_dir = training_dir / "raw"
    raw_dir.mkdir(parents=True)
    profiles_dir = tmp_path / "voice_profiles"
    monkeypatch.setattr(settings.cover_analysis, "training_data_dir", str(training_dir))
    monkeypatch.setattr(settings.cover_analysis, "voice_profiles_dir", str(profiles_dir))
    return raw_dir, profiles_dir


def _write_sine(path: Path, freq_hz: float = 440.0, seconds: float = 1.0,
                sr: int = 22050) -> Path:
    t = np.arange(int(seconds * sr)) / sr
    sf.write(str(path), (0.4 * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32), sr)
    return path


class _CountingAnalyzer:
    """固定画像 + 调用计数（缓存命中/失效与抽样上限断言用）。"""

    def __init__(self):
        self.calls = 0

    def __call__(self, audio_path, f0_confidence: float = 0.6) -> VoiceProfile:
        self.calls += 1
        return VoiceProfile(
            f0_median_hz=440.0,
            f0_median_midi=69.0,
            range_low_midi=64.0,
            range_high_midi=74.0,
            range_span_semitones=10.0,
            voiced_ratio=0.9,
        )


# ---------------------------------------------------------------------------
# None 语义（冻结契约）
# ---------------------------------------------------------------------------
def test_empty_source_returns_none(profile_env):
    """raw/ 存在但无 speaker 目录 / speaker 目录无 wav → None，不抛错。"""
    raw_dir, profiles_dir = profile_env
    assert store.get_profile("someone") is None
    (raw_dir / "empty_speaker").mkdir()
    assert store.get_profile("empty_speaker") is None
    assert store.list_profiles() == []
    assert not (profiles_dir / "someone.json").exists(), "空数据源不得写缓存"


@pytest.mark.parametrize("bad", ["", "张三", "..", "a/b", "  "])
def test_invalid_speaker_name_returns_none(profile_env, bad):
    """非法名（空/清洗后为空/映射目录不存在）→ None，不抛错。"""
    assert store.get_profile(bad) is None


def test_traversal_input_sanitized_to_alias_no_traversal(profile_env):
    """含穿越片段的输入按 so-vits 清洗惯例映射为白名单别名（无穿越可能）：
    '../evil' 清洗为 'evil'，命中同名 speaker 的画像而非越界目录。"""
    raw_dir, _ = profile_env
    (raw_dir / "evil").mkdir()
    _write_sine(raw_dir / "evil" / "a.wav", seconds=0.1, sr=8000)
    via_alias = store.get_profile("../evil")
    direct = store.get_profile("evil")
    assert via_alias is not None
    assert via_alias == direct
    assert via_alias["speaker_name"] == "evil"


def test_non_wav_files_ignored(profile_env):
    """目录内仅有非 wav 文件 → 视为空数据源 → None。"""
    raw_dir, _ = profile_env
    spk = raw_dir / "txt_only"
    spk.mkdir()
    (spk / "not_audio.txt").write_text("placeholder", encoding="utf-8")
    assert store.get_profile("txt_only") is None


# ---------------------------------------------------------------------------
# 真实分析链路（合成 440Hz）
# ---------------------------------------------------------------------------
def test_get_profile_real_analysis_and_cache_file(profile_env):
    """合成 440Hz wav → 真实 pyin 画像（median MIDI≈69）+ 缓存 JSON 落盘。"""
    raw_dir, profiles_dir = profile_env
    spk = raw_dir / "demo"
    spk.mkdir()
    _write_sine(spk / "a.wav", freq_hz=440.0)

    profile = store.get_profile("demo")
    assert profile is not None
    assert set(profile) == store.PROFILE_KEYS
    assert abs(profile["f0_median_midi"] - 69.0) <= 0.5
    assert abs(profile["f0_median_hz"] - 440.0) <= 5.0
    assert profile["sample_count"] == 1
    assert len(profile["dataset_md5"]) == 32
    assert profile["computed_at"]

    cache_file = profiles_dir / "demo.json"
    assert cache_file.exists(), "首次计算后必须落盘缓存"
    import json
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["dataset_md5"] == profile["dataset_md5"]


# ---------------------------------------------------------------------------
# 缓存命中 / 失效（计数器断言，不依赖重算耗时）
# ---------------------------------------------------------------------------
def test_cache_hit_skips_recompute(profile_env, monkeypatch):
    """MD5 不变二次调用不重算：analyzer 调用数不增长、computed_at 不变。"""
    raw_dir, _ = profile_env
    spk = raw_dir / "cached"
    spk.mkdir()
    _write_sine(spk / "a.wav")
    analyzer = _CountingAnalyzer()
    monkeypatch.setattr(store, "analyze_pitch", analyzer)

    first = store.get_profile("cached")
    assert analyzer.calls == 1, "首次必须重算"
    second = store.get_profile("cached")
    assert analyzer.calls == 1, "MD5 不变二次调用必须命中缓存跳过重算"
    assert second["computed_at"] == first["computed_at"]
    assert second["dataset_md5"] == first["dataset_md5"]


def test_cache_invalidated_by_mtime_change(profile_env, monkeypatch):
    """wav mtime 变化 → 数据集 MD5 变化 → 重算（调用数增长）。"""
    raw_dir, _ = profile_env
    spk = raw_dir / "invalidate"
    spk.mkdir()
    wav = _write_sine(spk / "a.wav")
    analyzer = _CountingAnalyzer()
    monkeypatch.setattr(store, "analyze_pitch", analyzer)

    first = store.get_profile("invalidate")
    assert analyzer.calls == 1
    st = wav.stat()
    os.utime(wav, (st.st_atime, st.st_mtime + 10))
    second = store.get_profile("invalidate")
    assert analyzer.calls == 2, "MD5 变化必须重算"
    assert second["dataset_md5"] != first["dataset_md5"]
    assert second["computed_at"] != first["computed_at"]


def test_cache_not_written_when_all_unanalyzable(profile_env, monkeypatch):
    """全部文件不可算 → None，且不写缓存。"""
    raw_dir, profiles_dir = profile_env
    spk = raw_dir / "broken"
    spk.mkdir()
    _write_sine(spk / "a.wav")

    def _raise(audio_path, f0_confidence: float = 0.6):
        raise VoiceAnalysisError("voiced frames too few")

    monkeypatch.setattr(store, "analyze_pitch", _raise)
    assert store.get_profile("broken") is None
    assert not (profiles_dir / "broken.json").exists()


# ---------------------------------------------------------------------------
# 抽样上限
# ---------------------------------------------------------------------------
def test_sampling_cap_limits_analysis(profile_env, monkeypatch):
    """wav 数超上限时均匀抽样：sample_count 与 analyzer 调用数均等于上限。"""
    raw_dir, _ = profile_env
    spk = raw_dir / "many"
    spk.mkdir()
    for i in range(6):
        _write_sine(spk / f"w{i}.wav", seconds=0.1, sr=8000)
    analyzer = _CountingAnalyzer()
    monkeypatch.setattr(store, "analyze_pitch", analyzer)
    monkeypatch.setattr(store, "_MAX_ANALYZE_FILES", 3)

    profile = store.get_profile("many")
    assert profile["sample_count"] == 3
    assert analyzer.calls == 3


def test_sampling_disabled_when_below_cap(profile_env, monkeypatch):
    """wav 数不超上限时全量分析。"""
    raw_dir, _ = profile_env
    spk = raw_dir / "few"
    spk.mkdir()
    for i in range(2):
        _write_sine(spk / f"w{i}.wav", seconds=0.1, sr=8000)
    analyzer = _CountingAnalyzer()
    monkeypatch.setattr(store, "analyze_pitch", analyzer)
    monkeypatch.setattr(store, "_MAX_ANALYZE_FILES", 30)

    profile = store.get_profile("few")
    assert profile["sample_count"] == 2
    assert analyzer.calls == 2


# ---------------------------------------------------------------------------
# list_profiles（冻结契约）
# ---------------------------------------------------------------------------
def test_list_profiles_only_computable_sorted(profile_env, monkeypatch):
    """只返回有画像的 speaker，按名称升序，条目含 dataset_md5/computed_at。"""
    raw_dir, _ = profile_env
    (raw_dir / "beta").mkdir(exist_ok=True)
    _write_sine(raw_dir / "beta" / "a.wav", seconds=0.1, sr=8000)
    (raw_dir / "alpha").mkdir(exist_ok=True)
    _write_sine(raw_dir / "alpha" / "a.wav", seconds=0.1, sr=8000)
    (raw_dir / "empty").mkdir(exist_ok=True)  # 无画像 → 不出现

    analyzer = _CountingAnalyzer()
    monkeypatch.setattr(store, "analyze_pitch", analyzer)
    profiles = store.list_profiles()
    assert [p["speaker_name"] for p in profiles] == ["alpha", "beta"]
    for p in profiles:
        assert store.PROFILE_KEYS.issubset(p.keys())
        assert p["dataset_md5"] and p["computed_at"]


def test_list_profiles_missing_root_returns_empty(tmp_path, monkeypatch):
    """训练数据根不存在（跨服务目录缺失）→ 空列表不抛错。"""
    settings = get_settings()
    monkeypatch.setattr(
        settings.cover_analysis,
        "training_data_dir",
        str(tmp_path / "nonexistent" / "training"),
    )
    assert store.list_profiles() == []
