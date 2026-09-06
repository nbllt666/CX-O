"""cover analyze / model-profiles 端点测试（change-id: enhance-cover-pitch-analysis-duet SubTask 2.3）

覆盖：
- audio_path 白名单 = data/input：越界 400、白名单内文件不存在 400
- 纯人声合成音（440Hz wav）analyze 成功：profile 断言 + separation_used=False
- model_name 无画像 → 200 + profile_unavailable（不报错，spec 冻结行为）
- 有画像（tmp 注入 training_data_dir + 220Hz 预生成 wav）→ recommended_transpose=+12
- 推荐值钳制（±12）：超界双向钳到 12/-12
- range_warning：源跨度 > 目标跨度时附警告
- 分离引擎错误 → 503（mock VocalSeparator 抛 SeparationError）
- 分离后仍无法分析 → 400 可读错误
- GET /model-profiles：空列表 / 有画像条目（dataset_md5/computed_at）
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import numpy as np
import soundfile as sf
from httpx import ASGITransport, AsyncClient

import workstation.api.cover as cover_api
from workstation.config import get_settings
from workstation.main import create_app
from workstation.services import voice_profile_store as store
from workstation.services.vocal_analysis import VoiceProfile
from workstation.services.vocal_separator import SeparationError

PROFILE_UNAVAILABLE_TEXT = "模型训练数据不可得，无法推荐 transpose"


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """隔离 API 测试环境：input/训练数据/缓存目录均指向 tmp_path。"""
    settings = get_settings()
    input_dir = tmp_path / "input"
    input_dir.mkdir(parents=True)
    training_dir = tmp_path / "training"
    (training_dir / "raw").mkdir(parents=True)
    monkeypatch.setattr(settings.audio_upload, "input_dir", str(input_dir))
    monkeypatch.setattr(settings.cover_analysis, "training_data_dir", str(training_dir))
    monkeypatch.setattr(
        settings.cover_analysis, "voice_profiles_dir", str(tmp_path / "voice_profiles")
    )

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, input_dir, training_dir / "raw"


def _write_sine(path, freq_hz: float = 440.0, seconds: float = 2.0,
                sr: int = 22050) -> str:
    t = np.arange(int(seconds * sr)) / sr
    sf.write(str(path), (0.4 * np.sin(2.0 * np.pi * freq_hz * t)).astype(np.float32), sr)
    return str(path)


def _write_silence(path, seconds: float = 1.0, sr: int = 22050) -> str:
    sf.write(str(path), np.zeros(int(seconds * sr), dtype=np.float32), sr)
    return str(path)


def _fake_target_profile(midi: float = 57.0, span: float = 10.0) -> VoiceProfile:
    return VoiceProfile(
        f0_median_hz=440.0 * (2.0 ** ((midi - 69.0) / 12.0)),
        f0_median_midi=midi,
        range_low_midi=midi - span / 2.0,
        range_high_midi=midi + span / 2.0,
        range_span_semitones=span,
        voiced_ratio=0.9,
    )


class _StubSeparator:
    """可编程桩分离器：mode 决定 separate_vocal_accompaniment 行为。"""

    mode = "error"  # error → SeparationError；pass_silence → 返回静音产物

    def __init__(self, config=None):
        pass

    async def separate_vocal_accompaniment(self, audio_path):
        if self.mode == "error":
            raise SeparationError(
                "demucs",
                "引擎目录不存在: engines/demucs；"
                "请执行 python tools/setup_separation.py --clone 克隆引擎",
            )
        return _return_silence_pair()


_SILENCE_PATHS: list[str] = []


def _return_silence_pair():
    return _SILENCE_PATHS[0], _SILENCE_PATHS[1]


# ---------------------------------------------------------------------------
# 白名单
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_analyze_outside_whitelist_400(client):
    """audio_path 在 data/input 之外 → 400（白名单拒绝）。"""
    c, input_dir, _raw = client
    outside = input_dir.parent / "outside.wav"
    sf.write(str(outside), np.zeros(100, dtype=np.float32), 22050)
    resp = await c.post("/api/cover/analyze", json={"audio_path": str(outside)})
    assert resp.status_code == 400
    assert "白名单" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_analyze_missing_file_400(client):
    """audio_path 在白名单内但文件不存在 → 400。"""
    c, input_dir, _raw = client
    resp = await c.post(
        "/api/cover/analyze", json={"audio_path": str(input_dir / "nope.wav")}
    )
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 纯人声分析成功
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_analyze_pure_voice_success(client):
    """440Hz 纯人声：200 + profile（median MIDI≈69）+ separation_used=False。"""
    c, input_dir, _raw = client
    audio = _write_sine(input_dir / "a4.wav", freq_hz=440.0)
    resp = await c.post("/api/cover/analyze", json={"audio_path": audio})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["separation_used"] is False
    assert abs(body["profile"]["f0_median_midi"] - 69.0) <= 0.5
    assert body["profile"]["voiced_ratio"] > 0.0
    # 未给 model_name：不含推荐字段
    assert "recommended_transpose" not in body
    assert "profile_unavailable" not in body


# ---------------------------------------------------------------------------
# 目标画像：不可算 / 可算 / 钳制 / 覆盖警告
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_analyze_model_without_profile_200_unavailable(client):
    """model_name 无训练数据 → 200 + profile_unavailable（spec 冻结：不报错）。"""
    c, input_dir, _raw = client
    audio = _write_sine(input_dir / "a4.wav")
    resp = await c.post(
        "/api/cover/analyze", json={"audio_path": audio, "model_name": "ghost_model"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "success"
    assert body["model_name"] == "ghost_model"
    assert body["profile_unavailable"] == PROFILE_UNAVAILABLE_TEXT
    assert "recommended_transpose" not in body
    assert "target_profile" not in body


@pytest.mark.asyncio
async def test_analyze_with_profile_recommends_plus_12(client):
    """440Hz 源（MIDI 69）vs 220Hz 目标（MIDI 57）→ 推荐 +12。"""
    c, input_dir, raw = client
    audio = _write_sine(input_dir / "a4.wav", freq_hz=440.0)
    target_dir = raw / "target_model"
    target_dir.mkdir()
    _write_sine(target_dir / "train.wav", freq_hz=220.0, seconds=2.0)

    resp = await c.post(
        "/api/cover/analyze",
        json={"audio_path": audio, "model_name": "target_model"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "profile_unavailable" not in body
    assert body["model_name"] == "target_model"
    assert body["recommended_transpose"] == 12
    assert body["target_profile"]["speaker_name"] == "target_model"
    assert abs(body["target_profile"]["f0_median_midi"] - 57.0) <= 0.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target_midi,expected", [(40.0, 12), (95.0, -12)]
)
async def test_analyze_transpose_clamped(client, monkeypatch, target_midi, expected):
    """推荐值超 ±12 时钳制：源 69 - 目标 40 = 29 → 12；69 - 95 = -26 → -12。"""
    c, input_dir, raw = client
    audio = _write_sine(input_dir / "a4.wav")
    (raw / "clamped_model").mkdir()
    _write_silence(raw / "clamped_model" / "train.wav", seconds=0.1)
    monkeypatch.setattr(
        store, "analyze_pitch", lambda p, f0_confidence=0.6: _fake_target_profile(target_midi)
    )
    resp = await c.post(
        "/api/cover/analyze",
        json={"audio_path": audio, "model_name": "clamped_model"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["recommended_transpose"] == expected


@pytest.mark.asyncio
async def test_analyze_range_warning_when_source_wider(client, monkeypatch):
    """源音域跨度 > 目标跨度 → range_warning 含双方跨度值。

    源为 440Hz+880Hz 双音高合成音（真实跨度 ≈12 半音，确定性大于 0），
    目标画像（假分析器）跨度精确 0 → 必触发警告。
    """
    c, input_dir, raw = client
    sr = 22050
    t_a = np.arange(sr) / sr
    t_b = np.arange(sr) / sr
    y = np.concatenate(
        [
            0.4 * np.sin(2.0 * np.pi * 440.0 * t_a),
            0.4 * np.sin(2.0 * np.pi * 880.0 * t_b),
        ]
    ).astype(np.float32)
    audio = str(input_dir / "wide.wav")
    sf.write(audio, y, sr)

    (raw / "narrow_model").mkdir()
    _write_silence(raw / "narrow_model" / "train.wav", seconds=0.1)
    monkeypatch.setattr(
        store, "analyze_pitch", lambda p, f0_confidence=0.6: _fake_target_profile(57.0, span=0.0)
    )
    resp = await c.post(
        "/api/cover/analyze",
        json={"audio_path": audio, "model_name": "narrow_model"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "range_warning" in body
    warning = body["range_warning"]
    assert f"{body['profile']['range_span_semitones']:.1f}" in warning
    assert "0.0" in warning


# ---------------------------------------------------------------------------
# 分离链路错误
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_analyze_separation_error_503(client, monkeypatch):
    """无声输入触发分离回退，引擎错误（mock）→ 503 含 setup 指引。"""
    c, input_dir, _raw = client
    audio = _write_silence(input_dir / "silence.wav")
    monkeypatch.setattr(cover_api, "VocalSeparator", _StubSeparator)

    resp = await c.post("/api/cover/analyze", json={"audio_path": audio})
    assert resp.status_code == 503, resp.text
    assert "setup_separation.py" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_analyze_still_unanalyzable_after_separation_400(client, monkeypatch):
    """voiced 不达标且分离（mock 返回静音产物）后仍不达标 → 400 可读错误。"""
    c, input_dir, _raw = client
    audio = _write_silence(input_dir / "silence.wav")
    _SILENCE_PATHS.clear()
    _SILENCE_PATHS.append(_write_silence(input_dir / "sep_vocals.wav"))
    _SILENCE_PATHS.append(_write_silence(input_dir / "sep_acc.wav"))
    monkeypatch.setattr(cover_api, "VocalSeparator", _StubSeparator)
    _StubSeparator.mode = "pass_silence"

    try:
        resp = await c.post("/api/cover/analyze", json={"audio_path": audio})
        assert resp.status_code == 400, resp.text
        assert "音域分析失败" in resp.json()["detail"]
    finally:
        _StubSeparator.mode = "error"


# ---------------------------------------------------------------------------
# GET /model-profiles
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_model_profiles_empty(client):
    """无训练数据 → 空画像列表。"""
    c, _input, _raw = client
    resp = await c.get("/api/cover/model-profiles")
    assert resp.status_code == 200
    assert resp.json() == {"status": "success", "profiles": []}


@pytest.mark.asyncio
async def test_model_profiles_with_entries(client, monkeypatch):
    """有训练数据的 speaker 出现在列表，含 dataset_md5/computed_at。"""
    c, _input, raw = client
    (raw / "listed_model").mkdir()
    _write_silence(raw / "listed_model" / "train.wav", seconds=0.1)
    monkeypatch.setattr(
        store, "analyze_pitch", lambda p, f0_confidence=0.6: _fake_target_profile(60.0)
    )
    resp = await c.get("/api/cover/model-profiles")
    assert resp.status_code == 200
    profiles = resp.json()["profiles"]
    assert len(profiles) == 1
    entry = profiles[0]
    assert entry["speaker_name"] == "listed_model"
    assert abs(entry["f0_median_midi"] - 60.0) < 1e-6
    assert len(entry["dataset_md5"]) == 32
    assert entry["computed_at"]
