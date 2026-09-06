"""
歌声合成引擎适配层测试：Mock 正弦合成、DiffSinger 子进程路径、未部署报错、引擎工厂选择
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from workstation.config import MusicConfig
from workstation.music.score import total_beats, validate_score
from workstation.services.singing_engine import (
    DiffSingerEngine,
    MockSingingEngine,
    SingingEngine,
    SingingEngineError,
    check_diffsinger_deployment,
    create_singing_engine,
)
import workstation.services.singing_engine as singing_engine_module


def _minimal_score() -> dict:
    """构造一份通过 validate_score 校验的最小歌谱（2 音符、120 BPM、共 2 拍）"""
    ok, errors, score = validate_score(
        {
            "title": "引擎测试",
            "bpm": 120,
            "melody": [
                {"pitch": "C4", "beats": 1.0, "lyric": "你"},
                {"pitch": "E4", "beats": 1.0, "lyric": "好"},
            ],
        }
    )
    assert ok, f"最小歌谱应通过校验: {errors}"
    return score


class TestMockSingingEngine:
    """Mock 正弦歌声合成用例"""

    def test_produces_valid_wav(self, tmp_path: Path):
        score = _minimal_score()
        engine = MockSingingEngine()
        out = engine.synthesize(score, "", tmp_path / "raw_vocal.wav")

        assert out.is_file()
        with wave.open(str(out), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 44100
            n_frames = wf.getnframes()
            frames = wf.readframes(n_frames)

        # 时长与歌谱总节拍一致（逐音符取整，误差不超过每音符 1 帧）
        expected_frames = total_beats(score) * 60.0 / score["bpm"] * 44100
        assert abs(n_frames - expected_frames) <= len(score["melody"])
        # 非全零（确有可闻信号）
        assert any(frames)

    def test_deterministic_output(self, tmp_path: Path):
        score = _minimal_score()
        engine = MockSingingEngine()
        out1 = engine.synthesize(score, "", tmp_path / "a.wav")
        out2 = engine.synthesize(score, "", tmp_path / "b.wav")
        assert out1.read_bytes() == out2.read_bytes()

    def test_creates_parent_dirs(self, tmp_path: Path):
        engine = MockSingingEngine()
        out = engine.synthesize(_minimal_score(), "", tmp_path / "nested" / "dir" / "vocal.wav")
        assert out.is_file()

    def test_sample_rate_configurable(self, tmp_path: Path):
        engine = MockSingingEngine(sample_rate=22050)
        out = engine.synthesize(_minimal_score(), "", tmp_path / "low.wav")
        with wave.open(str(out), "rb") as wf:
            assert wf.getframerate() == 22050

    def test_invalid_score_rejected(self, tmp_path: Path):
        engine = MockSingingEngine()
        with pytest.raises(ValueError, match="bpm"):
            engine.synthesize({"title": "x", "bpm": 0, "melody": [{"pitch": "C4", "beats": 1}]}, "", tmp_path / "x.wav")
        with pytest.raises(ValueError, match="melody"):
            engine.synthesize({"title": "x", "bpm": 120, "melody": []}, "", tmp_path / "x.wav")
        with pytest.raises(ValueError, match="音高"):
            engine.synthesize({"title": "x", "bpm": 120, "melody": [{"pitch": "H9", "beats": 1}]}, "", tmp_path / "x.wav")


class TestDiffSingerEngine:
    """DiffSinger 未部署报错用例（本环境无真实部署，不触发子进程）"""

    def test_missing_dir_error_lists_items(self, tmp_path: Path):
        missing_dir = tmp_path / "no_such_diffsinger"
        engine = DiffSingerEngine(str(missing_dir), "python", "mybank")
        with pytest.raises(SingingEngineError) as exc_info:
            engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")
        message = str(exc_info.value)
        assert str(missing_dir) in message
        assert "mybank" in message
        assert "setup_singing_engine" in message

    def test_unconfigured_voice_bank_listed(self, tmp_path: Path):
        # 目录存在但声库未配置
        engine = DiffSingerEngine(str(tmp_path), sys.executable, "")
        with pytest.raises(SingingEngineError) as exc_info:
            engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")
        assert "声库未配置" in str(exc_info.value)

    def test_constructor_does_not_raise_on_missing(self, tmp_path: Path):
        # 构造期不检查部署，允许先实例化
        engine = DiffSingerEngine(str(tmp_path / "ghost"), "python", "b")
        assert isinstance(engine, SingingEngine)

    def test_check_deployment_all_ready(self, tmp_path: Path):
        (tmp_path / "voicebanks" / "mybank").mkdir(parents=True)
        missing = check_diffsinger_deployment(str(tmp_path), sys.executable, "mybank")
        assert missing == []

    def test_check_deployment_missing_python_path(self, tmp_path: Path):
        missing = check_diffsinger_deployment(str(tmp_path), str(tmp_path / "no_python.exe"), "")
        assert any("Python 解释器不存在" in item for item in missing)

    def test_check_deployment_python_in_path(self, tmp_path: Path, monkeypatch):
        # python 配置为 PATH 中的命令名（非路径、无 .exe 后缀），shutil.which 能找到
        (tmp_path / "voicebanks" / "mybank").mkdir(parents=True)
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: str(tmp_path / "fake_python"))
        missing = check_diffsinger_deployment(str(tmp_path), "python", "mybank")
        assert missing == []

    def test_check_deployment_python_not_in_path(self, tmp_path: Path, monkeypatch):
        # python 命令名不在 PATH 中 → 缺失项含 "不在 PATH 中"
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: None)
        missing = check_diffsinger_deployment(str(tmp_path), "python", "mybank")
        assert any("不在 PATH 中" in item for item in missing)


# ---------------------------------------------------------------------------
# DiffSinger 子进程成功/失败路径（mock subprocess.run，免真实部署）
# ---------------------------------------------------------------------------


def _write_minimal_wav(path: Path, seconds: float = 0.5, rate: int = 44100) -> Path:
    """写最小合法 WAV（16bit 单声道正弦），供 fake subprocess 产出"""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, int(round(seconds * rate)))
    scale = 0.2 * 32767.0
    step = 2.0 * math.pi * 220.0 / rate
    pcm = struct.pack(f"<{n}h", *(int(scale * math.sin(step * i)) for i in range(n)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframesraw(pcm)
    return path


def _make_ready_engine(tmp_path: Path, **overrides) -> DiffSingerEngine:
    """构造部署就绪的 DiffSingerEngine：tmp_path 作为 diffsinger_dir，voicebanks/mybank 已创建"""
    (tmp_path / "voicebanks" / "mybank").mkdir(parents=True, exist_ok=True)
    defaults = dict(
        diffsinger_dir=str(tmp_path),
        diffsinger_python=sys.executable,
        voice_bank="mybank",
    )
    defaults.update(overrides)
    return DiffSingerEngine(**defaults)


def _fake_run_writing_output(*args, **kwargs):
    """伪造 subprocess.run：解析 --output 参数路径并写合法 WAV，返回 returncode=0"""
    cmd = args[0] if args else kwargs.get("args")
    out_idx = cmd.index("--output") + 1
    _write_minimal_wav(Path(cmd[out_idx]))
    return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="synth ok", stderr="")


class TestDiffSingerSubprocess:
    """DiffSinger 子进程调用路径用例（mock subprocess.run，验证命令行/参数/产出/错误处理）"""

    def test_synthesize_success_returns_output_path(self, tmp_path: Path, monkeypatch):
        """部署就绪 + 子进程返回 0 + 产出 WAV → synthesize 返回产出路径"""
        monkeypatch.setattr(singing_engine_module.subprocess, "run", _fake_run_writing_output)
        engine = _make_ready_engine(tmp_path)
        out = engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")

        assert out == tmp_path / "out.wav"
        assert out.is_file()
        # 产出是合法 WAV
        with wave.open(str(out), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 44100

    def test_subprocess_command_args(self, tmp_path: Path, monkeypatch):
        """子进程命令行：python voicews_inference.py --score <json> --voice_bank <path> --output <path>"""
        captured: dict = {}

        def capturing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            captured["cmd"] = list(cmd)
            captured["cwd"] = kwargs.get("cwd")
            captured["timeout"] = kwargs.get("timeout")
            return _fake_run_writing_output(*args, **kwargs)

        monkeypatch.setattr(singing_engine_module.subprocess, "run", capturing_run)
        engine = _make_ready_engine(tmp_path)
        out_path = tmp_path / "nested" / "vocal.wav"
        engine.synthesize(_minimal_score(), "", out_path)

        cmd = captured["cmd"]
        assert cmd[0] == sys.executable
        assert cmd[1] == "voicews_inference.py"
        assert "--score" in cmd
        assert "--voice_bank" in cmd
        assert "--output" in cmd
        # --output 值为输出路径
        assert cmd[cmd.index("--output") + 1] == str(out_path)
        # --voice_bank 值为解析后的声库绝对路径（voicebanks/mybank）
        bank_arg = cmd[cmd.index("--voice_bank") + 1]
        assert Path(bank_arg).resolve() == (tmp_path / "voicebanks" / "mybank").resolve()
        # cwd = diffsinger_dir
        assert captured["cwd"] == str(tmp_path)
        # timeout 传递
        assert captured["timeout"] == 300.0

    def test_score_file_written_and_cleaned_up(self, tmp_path: Path, monkeypatch):
        """临时 score JSON 文件写入后于 finally 清理（不留残留）"""
        score_paths: list[str] = []

        def inspect_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            score_path = cmd[cmd.index("--score") + 1]
            score_paths.append(score_path)
            # 验证调用时 score 文件存在且内容正确
            assert Path(score_path).is_file()
            data = json.loads(Path(score_path).read_text(encoding="utf-8"))
            assert data["bpm"] == 120
            assert len(data["melody"]) == 2
            return _fake_run_writing_output(*args, **kwargs)

        monkeypatch.setattr(singing_engine_module.subprocess, "run", inspect_run)
        engine = _make_ready_engine(tmp_path)
        engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")

        # 调用结束后临时文件已清理
        assert len(score_paths) == 1
        assert not Path(score_paths[0]).exists()

    def test_nonzero_exit_raises_with_stderr_tail(self, tmp_path: Path, monkeypatch):
        """子进程非零退出码 → SingingEngineError 含退出码与 stderr 尾部"""
        def failing_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            return subprocess.CompletedProcess(
                args=cmd, returncode=3, stdout="", stderr="Traceback ... RuntimeError: boom"
            )

        monkeypatch.setattr(singing_engine_module.subprocess, "run", failing_run)
        engine = _make_ready_engine(tmp_path)
        with pytest.raises(SingingEngineError) as exc_info:
            engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")
        msg = str(exc_info.value)
        assert "退出码 3" in msg
        assert "boom" in msg
        # 失败时不产出文件
        assert not (tmp_path / "out.wav").exists()

    def test_missing_output_file_raises(self, tmp_path: Path, monkeypatch):
        """子进程返回 0 但未产出文件 → SingingEngineError"""
        def no_output_run(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(singing_engine_module.subprocess, "run", no_output_run)
        engine = _make_ready_engine(tmp_path)
        with pytest.raises(SingingEngineError, match="未产出文件"):
            engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")

    def test_subprocess_timeout_raises(self, tmp_path: Path, monkeypatch):
        """子进程超时 → SingingEngineError 含超时秒数"""
        def timeout_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 300))

        monkeypatch.setattr(singing_engine_module.subprocess, "run", timeout_run)
        engine = _make_ready_engine(tmp_path, subprocess_timeout=5.0)
        with pytest.raises(SingingEngineError) as exc_info:
            engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")
        assert ">5s" in str(exc_info.value)

    def test_voice_bank_absolute_path(self, tmp_path: Path, monkeypatch):
        """voice_bank 为绝对路径时按原样传递给子进程（不走 voicebanks/ 拼接）"""
        bank_dir = tmp_path / "custom_bank"
        bank_dir.mkdir()
        captured: list[str] = []

        def capture_bank(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            captured.append(cmd[cmd.index("--voice_bank") + 1])
            return _fake_run_writing_output(*args, **kwargs)

        monkeypatch.setattr(singing_engine_module.subprocess, "run", capture_bank)
        engine = _make_ready_engine(tmp_path, voice_bank=str(bank_dir))
        engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")
        assert captured[0] == str(bank_dir)

    def test_voice_bank_override_in_synthesize(self, tmp_path: Path, monkeypatch):
        """synthesize 的 voice_bank 参数覆盖构造期配置"""
        (tmp_path / "voicebanks" / "other").mkdir(parents=True)
        captured: list[str] = []

        def capture_bank(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            captured.append(cmd[cmd.index("--voice_bank") + 1])
            return _fake_run_writing_output(*args, **kwargs)

        monkeypatch.setattr(singing_engine_module.subprocess, "run", capture_bank)
        engine = _make_ready_engine(tmp_path, voice_bank="mybank")
        # synthesize 传入 other 覆盖构造期 mybank
        engine.synthesize(_minimal_score(), "other", tmp_path / "out.wav")
        assert Path(captured[0]).resolve() == (tmp_path / "voicebanks" / "other").resolve()

    def test_creates_parent_dirs_for_output(self, tmp_path: Path, monkeypatch):
        """输出路径父目录不存在时自动创建"""
        monkeypatch.setattr(singing_engine_module.subprocess, "run", _fake_run_writing_output)
        engine = _make_ready_engine(tmp_path)
        out = tmp_path / "deep" / "nested" / "dir" / "vocal.wav"
        result = engine.synthesize(_minimal_score(), "", out)
        assert result.is_file()

    def test_invalid_score_rejected_before_subprocess(self, tmp_path: Path, monkeypatch):
        """非法歌谱在子进程调用前拦截（不触发 subprocess.run）"""
        called: list[bool] = []

        def should_not_run(*args, **kwargs):
            called.append(True)
            return _fake_run_writing_output(*args, **kwargs)

        monkeypatch.setattr(singing_engine_module.subprocess, "run", should_not_run)
        engine = _make_ready_engine(tmp_path)
        with pytest.raises(ValueError, match="melody"):
            engine.synthesize({"title": "x", "bpm": 120, "melody": []}, "", tmp_path / "out.wav")
        assert called == []


class TestCreateSingingEngine:
    """引擎工厂用例"""

    def test_factory_returns_mock(self):
        engine = create_singing_engine(MusicConfig(singing_engine="mock"))
        assert isinstance(engine, MockSingingEngine)

    def test_factory_returns_diffsinger(self):
        cfg = MusicConfig(
            singing_engine="diffsinger",
            diffsinger_dir="D:/ds",
            diffsinger_python="python",
            voice_bank="vb",
        )
        engine = create_singing_engine(cfg)
        assert isinstance(engine, DiffSingerEngine)

    def test_factory_case_insensitive(self):
        assert isinstance(create_singing_engine(MusicConfig(singing_engine="MOCK")), MockSingingEngine)
        assert isinstance(create_singing_engine(MusicConfig(singing_engine=" DiffSinger ")), DiffSingerEngine)

    def test_factory_default_config_is_diffsinger(self):
        # config=None 时读取全局配置，默认 singing_engine="diffsinger"（spec 真实引擎接入要求）
        engine = create_singing_engine(None)
        assert isinstance(engine, DiffSingerEngine)

    def test_factory_unknown_raises(self):
        with pytest.raises(ValueError, match="未知歌声合成引擎"):
            create_singing_engine(MusicConfig(singing_engine="utau"))

    def test_factory_diffsinger_synthesize_reports_missing(self, tmp_path: Path):
        cfg = MusicConfig(
            singing_engine="diffsinger",
            diffsinger_dir=str(tmp_path / "ghost"),
            diffsinger_python=sys.executable,
            voice_bank="lostbank",
        )
        engine = create_singing_engine(cfg)
        with pytest.raises(SingingEngineError) as exc_info:
            engine.synthesize(_minimal_score(), "", tmp_path / "out.wav")
        message = str(exc_info.value)
        assert str(tmp_path / "ghost") in message
        assert "lostbank" in message

    def test_abstract_base_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SingingEngine()  # type: ignore[abstract]
