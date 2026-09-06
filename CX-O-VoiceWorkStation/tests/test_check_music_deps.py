"""
Task 8「check_music_deps.py 依赖检查」单元测试

对应 spec：refactor-audiostation-engine-consolidation（Task 8 SubTask 8.2）。

覆盖：
- _check_music21：music21 可导入 → True；mock 导入失败 → False + 修复指引
- _check_fluidsynth：PATH 中可用 → True；不在 PATH → False + 修复指引
- _check_soundfont：未配置 / 文件不存在 / 文件存在 三态
- main：全部就绪 → 退出码 0；存在缺失项 → 退出码 1
"""
from __future__ import annotations

import os
import sys

import pytest

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

import workstation.config as config_module  # noqa: E402
import workstation.tools.check_music_deps as deps_module  # noqa: E402
from workstation.config import WorkstationSettings  # noqa: E402


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _make_settings(soundfont_path: str = "") -> WorkstationSettings:
    """构造隔离的 WorkstationSettings（仅 soundfont_path 可控）"""
    settings = WorkstationSettings()
    settings.music.soundfont_path = soundfont_path
    return settings


# ---------------------------------------------------------------------------
# _check_music21
# ---------------------------------------------------------------------------


class TestCheckMusic21:
    def test_music21_available(self, capsys):
        """music21 已安装 → True，INFO 输出含版本"""
        assert deps_module._check_music21() is True
        out = capsys.readouterr().out
        assert "[INFO]" in out
        assert "music21" in out

    def test_music21_import_failure(self, monkeypatch, capsys):
        """mock music21 导入失败 → False，错误含 pip install 修复指引"""
        # sys.modules[name]=None 使 import 抛 ImportError（CPython 文档化行为）
        monkeypatch.setitem(sys.modules, "music21", None)
        assert deps_module._check_music21() is False
        out = capsys.readouterr().out
        assert "[ERROR]" in out
        assert "music21" in out
        assert "pip install music21" in out


# ---------------------------------------------------------------------------
# _check_fluidsynth
# ---------------------------------------------------------------------------


class TestCheckFluidsynth:
    def test_fluidsynth_available(self, monkeypatch, capsys):
        """fluidsynth 在 PATH 中 → True，INFO 输出含可执行文件路径"""
        monkeypatch.setattr(deps_module.shutil, "which", lambda cmd: "/usr/bin/fluidsynth")
        assert deps_module._check_fluidsynth() is True
        out = capsys.readouterr().out
        assert "[INFO]" in out
        assert "fluidsynth 可用" in out
        assert "/usr/bin/fluidsynth" in out

    def test_fluidsynth_missing(self, monkeypatch, capsys):
        """fluidsynth 不在 PATH → False，错误含 PATH 与安装指引"""
        monkeypatch.setattr(deps_module.shutil, "which", lambda cmd: None)
        assert deps_module._check_fluidsynth() is False
        out = capsys.readouterr().out
        assert "[ERROR]" in out
        assert "fluidsynth" in out
        assert "PATH" in out
        assert "FluidSynth" in out  # 修复指引含安装说明


# ---------------------------------------------------------------------------
# _check_soundfont
# ---------------------------------------------------------------------------


class TestCheckSoundfont:
    def test_unconfigured(self, monkeypatch, capsys):
        """soundfont_path 为空 → False，错误含 soundfont_path 与「为空」"""
        monkeypatch.setattr(config_module, "get_settings", lambda: _make_settings(""))
        assert deps_module._check_soundfont() is False
        out = capsys.readouterr().out
        assert "[ERROR]" in out
        assert "soundfont_path" in out
        assert "为空" in out

    def test_file_not_exist(self, monkeypatch, capsys):
        """配置了路径但文件不存在 → False，错误含路径与「不存在」"""
        missing = "/no/such/dir/piano.sf2"
        monkeypatch.setattr(config_module, "get_settings", lambda: _make_settings(missing))
        assert deps_module._check_soundfont() is False
        out = capsys.readouterr().out
        assert "[ERROR]" in out
        assert missing in out
        assert "不存在" in out

    def test_file_exists(self, monkeypatch, tmp_path, capsys):
        """配置了存在的 SoundFont 文件 → True，INFO 输出含路径"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-soundfont")
        monkeypatch.setattr(config_module, "get_settings", lambda: _make_settings(str(sf)))
        assert deps_module._check_soundfont() is True
        out = capsys.readouterr().out
        assert "[INFO]" in out
        assert "SoundFont 文件存在" in out
        assert str(sf) in out


# ---------------------------------------------------------------------------
# main 退出码
# ---------------------------------------------------------------------------


class TestMainExitCode:
    def test_all_ready_returns_zero(self, monkeypatch, tmp_path):
        """music21 + fluidsynth + SoundFont 全部就绪 → 退出码 0"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-soundfont")
        monkeypatch.setattr(deps_module.shutil, "which", lambda cmd: "/usr/bin/fluidsynth")
        monkeypatch.setattr(config_module, "get_settings", lambda: _make_settings(str(sf)))
        assert deps_module.main() == 0

    def test_missing_returns_one(self, monkeypatch):
        """fluidsynth 与 SoundFont 均缺失 → 退出码 1"""
        monkeypatch.setattr(deps_module.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(config_module, "get_settings", lambda: _make_settings(""))
        assert deps_module.main() == 1

    def test_partial_missing_returns_one(self, monkeypatch, tmp_path):
        """仅 soundfont 配置就绪但 fluidsynth 缺失 → 退出码 1"""
        sf = tmp_path / "piano.sf2"
        sf.write_bytes(b"fake-soundfont")
        monkeypatch.setattr(deps_module.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(config_module, "get_settings", lambda: _make_settings(str(sf)))
        assert deps_module.main() == 1
