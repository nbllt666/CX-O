"""config 新段单测（change-id: enhance-cover-pitch-analysis-duet SubTask 1.6）

覆盖 separation / cover_analysis 两段的默认值（auto_fill）、越界钳制与空回退。
"""
from __future__ import annotations

from workstation.config import (
    _BASE_DIR,
    CoverAnalysisConfig,
    SeparationConfig,
    WorkstationSettings,
)


# ---------------------------------------------------------------------------
# SeparationConfig 默认值（auto_fill）
# ---------------------------------------------------------------------------
def test_separation_defaults():
    cfg = SeparationConfig()
    assert cfg.enabled is True
    assert cfg.demucs_engine_dir == str(_BASE_DIR / "engines" / "demucs")
    assert cfg.audiosep_engine_dir == str(_BASE_DIR / "engines" / "AudioSep")
    assert cfg.demucs_python_path == "python"
    assert cfg.audiosep_python_path == "python"
    assert cfg.device == "auto"
    assert cfg.demucs_model == "htdemucs"
    assert cfg.audiosep_checkpoint == ""
    assert cfg.separation_dir == str(_BASE_DIR / "data" / "separation")
    assert cfg.subprocess_timeout_seconds == 600.0


def test_separation_device_invalid_falls_back_to_auto():
    assert SeparationConfig(device="tpu").device == "auto"
    assert SeparationConfig(device="").device == "auto"
    assert SeparationConfig(device="cuda").device == "cuda"
    assert SeparationConfig(device="cpu").device == "cpu"


def test_separation_timeout_clamped():
    assert SeparationConfig(subprocess_timeout_seconds=-5).subprocess_timeout_seconds == 1.0
    assert SeparationConfig(subprocess_timeout_seconds=0).subprocess_timeout_seconds == 1.0
    assert SeparationConfig(subprocess_timeout_seconds=999999).subprocess_timeout_seconds == 3600.0
    # 非数值回退默认
    assert SeparationConfig(subprocess_timeout_seconds="abc").subprocess_timeout_seconds == 600.0


def test_separation_checkpoint_whitespace_stripped():
    assert SeparationConfig(audiosep_checkpoint="  ").audiosep_checkpoint == ""
    assert SeparationConfig(
        audiosep_checkpoint=" C:/models/a.ckpt "
    ).audiosep_checkpoint == "C:/models/a.ckpt"


# ---------------------------------------------------------------------------
# CoverAnalysisConfig 默认值与钳制
# ---------------------------------------------------------------------------
def test_cover_analysis_defaults():
    cfg = CoverAnalysisConfig()
    # 跨服务只读根：锚定项目根下的 CXO-ModelStation 训练数据
    assert cfg.training_data_dir == str(
        _BASE_DIR.parent / "CXO-ModelStation" / "data" / "training" / "sovits_svc"
    )
    assert cfg.voice_profiles_dir == str(_BASE_DIR / "data" / "voice_profiles")
    assert cfg.f0_confidence == 0.6


def test_cover_analysis_f0_confidence_clamped():
    assert CoverAnalysisConfig(f0_confidence=1.5).f0_confidence == 1.0
    assert CoverAnalysisConfig(f0_confidence=-0.2).f0_confidence == 0.0
    assert CoverAnalysisConfig(f0_confidence="bad").f0_confidence == 0.6
    assert CoverAnalysisConfig(f0_confidence=0.75).f0_confidence == 0.75


# ---------------------------------------------------------------------------
# WorkstationSettings 挂载
# ---------------------------------------------------------------------------
def test_settings_contains_new_sections():
    settings = WorkstationSettings()
    assert isinstance(settings.separation, SeparationConfig)
    assert isinstance(settings.cover_analysis, CoverAnalysisConfig)
    # 全局单例同样携带新段
    from workstation.config import get_settings
    assert isinstance(get_settings().separation, SeparationConfig)
    assert isinstance(get_settings().cover_analysis, CoverAnalysisConfig)
