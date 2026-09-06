"""vocal_separator 单测（change-id: enhance-cover-pitch-analysis-duet SubTask 1.6）

覆盖：
- 守卫：enabled=false / 引擎目录缺失 / 输入缺失 / checkpoint 缺失 → SeparationError（含指引）
- demucs 成功路径（mock 子进程产物）/ 非0退出（stderr 尾部）/ 产物缺失 / 超时 terminate
- AudioSep 成功路径（mock wrapper 子进程）与默认查询/参数透传
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import workstation.services.vocal_separator as vs_mod
from workstation.config import SeparationConfig
from workstation.services.vocal_separator import SeparationError, VocalSeparator


def _make_config(tmp_path: Path, **overrides) -> SeparationConfig:
    defaults = dict(
        enabled=True,
        demucs_engine_dir=str(tmp_path / "engines" / "demucs"),
        audiosep_engine_dir=str(tmp_path / "engines" / "AudioSep"),
        demucs_python_path="python",
        audiosep_python_path="python",
        device="auto",
        demucs_model="htdemucs",
        audiosep_checkpoint="",
        separation_dir=str(tmp_path / "separation"),
        subprocess_timeout_seconds=600.0,
    )
    defaults.update(overrides)
    return SeparationConfig(**defaults)


def _make_input(tmp_path: Path) -> Path:
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"RIFFfake")
    return audio


class _HangProc:
    """communicate() 挂起的假子进程（用于超时 terminate 链路验证）。"""

    def __init__(self):
        self.pid = 4242
        self.returncode = None
        self.terminated = False
        self.killed = False

    async def communicate(self):
        await asyncio.sleep(60)
        return b"", b""

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    async def wait(self):
        self.returncode = -15
        return self.returncode


# ---------------------------------------------------------------------------
# 守卫
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_guard_disabled_raises_with_hint(tmp_path):
    cfg = _make_config(tmp_path, enabled=False)
    sep = VocalSeparator(config=cfg)
    with pytest.raises(SeparationError, match="enabled=false"):
        await sep.separate_vocal_accompaniment(_make_input(tmp_path))


@pytest.mark.asyncio
async def test_guard_engine_missing_raises_with_setup_hint(tmp_path):
    cfg = _make_config(tmp_path)  # 引擎目录未创建
    sep = VocalSeparator(config=cfg)
    with pytest.raises(SeparationError, match="setup_separation.py --clone"):
        await sep.separate_vocal_accompaniment(_make_input(tmp_path))


@pytest.mark.asyncio
async def test_guard_input_missing(tmp_path):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "demucs").mkdir(parents=True)
    sep = VocalSeparator(config=cfg)
    with pytest.raises(SeparationError, match="not found"):
        await sep.separate_vocal_accompaniment(tmp_path / "missing.wav")


# ---------------------------------------------------------------------------
# demucs：成功 / 非0退出 / 产物缺失 / 超时
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_demucs_success_moves_and_renames(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "demucs").mkdir(parents=True)
    audio = _make_input(tmp_path)
    sep = VocalSeparator(config=cfg)

    async def fake_run(args, cwd, engine_name, timeout):
        # 模拟 demucs 子进程产物：<outdir>/<model>/<track>/vocals.wav + no_vocals.wav
        outdir = Path(args[args.index("-o") + 1])
        track_dir = outdir / cfg.demucs_model / "input"
        track_dir.mkdir(parents=True)
        (track_dir / "vocals.wav").write_bytes(b"v")
        (track_dir / "no_vocals.wav").write_bytes(b"o")
        return b"", b"", 0

    monkeypatch.setattr(
        vs_mod.VocalSeparator, "_run_subprocess", staticmethod(fake_run)
    )
    vocals, accompaniment = await sep.separate_vocal_accompaniment(audio)

    assert vocals.name == "vocals.wav" and vocals.exists()
    assert accompaniment.name == "accompaniment.wav" and accompaniment.exists()
    assert vocals.parent == accompaniment.parent
    assert vocals.parent.is_relative_to(Path(cfg.separation_dir))
    # demucs 中间产物目录已清理
    assert not (vocals.parent / "demucs").exists()


@pytest.mark.asyncio
async def test_demucs_nonzero_exit_reports_stderr_tail(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "demucs").mkdir(parents=True)
    sep = VocalSeparator(config=cfg)

    async def fake_run(args, cwd, engine_name, timeout):
        return b"", b"torch error ... model load failed", 1

    monkeypatch.setattr(
        vs_mod.VocalSeparator, "_run_subprocess", staticmethod(fake_run)
    )
    with pytest.raises(SeparationError) as exc_info:
        await sep.separate_vocal_accompaniment(_make_input(tmp_path))
    message = str(exc_info.value)
    assert "[demucs]" in message
    assert "exit=1" in message
    assert "model load failed" in message


@pytest.mark.asyncio
async def test_demucs_missing_output_raises(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "demucs").mkdir(parents=True)
    sep = VocalSeparator(config=cfg)

    async def fake_run(args, cwd, engine_name, timeout):
        return b"", b"", 0  # 声称成功但不产出

    monkeypatch.setattr(
        vs_mod.VocalSeparator, "_run_subprocess", staticmethod(fake_run)
    )
    with pytest.raises(SeparationError, match="产物缺失"):
        await sep.separate_vocal_accompaniment(_make_input(tmp_path))


@pytest.mark.asyncio
async def test_demucs_timeout_terminates_process(tmp_path, monkeypatch):
    """子进程挂起 → 超时后 terminate → SeparationError（超时语义）。"""
    cfg = _make_config(tmp_path, subprocess_timeout_seconds=0.05)
    (tmp_path / "engines" / "demucs").mkdir(parents=True)
    sep = VocalSeparator(config=cfg)
    proc = _HangProc()

    async def fake_create_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_exec)
    with pytest.raises(SeparationError, match="超时"):
        await sep.separate_vocal_accompaniment(_make_input(tmp_path))
    assert proc.terminated is True
    assert proc.killed is False  # wait() 正常返回，无需升级 kill


def test_communicate_timeout_kill_chain():
    """_communicate_with_timeout：terminate 后仍不退 → kill 兜底。"""

    class _StubbornProc(_HangProc):
        async def wait(self):  # terminate 后仍挂住 → 触发 kill
            await asyncio.sleep(60)

    proc = _StubbornProc()

    async def scenario():
        await vs_mod._communicate_with_timeout(proc, timeout=0.05)

    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(scenario())
    assert proc.terminated is True
    assert proc.killed is True


# ---------------------------------------------------------------------------
# AudioSep
# ---------------------------------------------------------------------------
def test_audiosep_checkpoint_missing_raises(tmp_path):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "AudioSep").mkdir(parents=True)
    sep = VocalSeparator(config=cfg)
    with pytest.raises(SeparationError) as exc_info:
        sep._resolve_audiosep_checkpoint()
    assert "[audiosep]" in str(exc_info.value)
    assert "DEPLOY-SEPARATION.md" in str(exc_info.value)


def test_audiosep_checkpoint_config_path_invalid_raises(tmp_path):
    cfg = _make_config(tmp_path, audiosep_checkpoint=str(tmp_path / "missing.ckpt"))
    sep = VocalSeparator(config=cfg)
    with pytest.raises(SeparationError, match="不存在"):
        sep._resolve_audiosep_checkpoint()


def test_audiosep_checkpoint_fallback_scan(tmp_path):
    """未配置 checkpoint 时扫描引擎 checkpoint/ 目录取最新 .ckpt。"""
    ckpt_dir = tmp_path / "engines" / "AudioSep" / "checkpoint"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "older.ckpt").write_bytes(b"a")
    (ckpt_dir / "audiosep_base_4M_steps.ckpt").write_bytes(b"b")
    cfg = _make_config(tmp_path)
    sep = VocalSeparator(config=cfg)
    assert sep._resolve_audiosep_checkpoint().name == "audiosep_base_4M_steps.ckpt"


@pytest.mark.asyncio
async def test_audiosep_success_with_args_passthrough(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "AudioSep").mkdir(parents=True)
    ckpt = tmp_path / "engines" / "AudioSep" / "checkpoint" / "audiosep.ckpt"
    ckpt.parent.mkdir(parents=True)
    ckpt.write_bytes(b"ckpt")
    runner = tmp_path / "audiosep_runner.py"
    runner.write_text("# fake runner")
    monkeypatch.setattr(vs_mod, "_AUDIODEP_RUNNER", runner)

    captured: dict = {}

    async def fake_run(args, cwd, engine_name, timeout):
        captured["args"] = args
        captured["cwd"] = cwd
        out_a = Path(args[args.index("--output-a") + 1])
        out_b = Path(args[args.index("--output-b") + 1])
        out_a.write_bytes(b"a")
        out_b.write_bytes(b"b")
        return b"AUDIOSEP_RUNNER_OK", b"", 0

    monkeypatch.setattr(
        vs_mod.VocalSeparator, "_run_subprocess", staticmethod(fake_run)
    )
    sep = VocalSeparator(config=cfg)
    part_a, part_b = await sep.split_duet_vocals(
        _make_input(tmp_path), query_a="the lead vocal", query_b="the second vocal"
    )

    assert part_a.name == "part_a.wav" and part_a.exists()
    assert part_b.name == "part_b.wav" and part_b.exists()
    args = [str(a) for a in captured["args"]]
    assert str(runner) in args
    assert "--checkpoint" in args and str(ckpt) in args
    assert "--query-a" in args and "the lead vocal" in args
    assert "--query-b" in args and "the second vocal" in args
    assert "--device" in args and "auto" in args
    assert str(Path(cfg.audiosep_engine_dir)) == str(captured["cwd"])


@pytest.mark.asyncio
async def test_audiosep_default_queries(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "AudioSep").mkdir(parents=True)
    ckpt_dir = tmp_path / "engines" / "AudioSep" / "checkpoint"
    ckpt_dir.mkdir(parents=True)
    (ckpt_dir / "audiosep.ckpt").write_bytes(b"ckpt")
    monkeypatch.setattr(
        vs_mod, "_AUDIODEP_RUNNER", tmp_path / "audiosep_runner.py"
    )
    (tmp_path / "audiosep_runner.py").write_text("# fake runner")

    captured: dict = {}

    async def fake_run(args, cwd, engine_name, timeout):
        captured["args"] = [str(a) for a in args]
        Path(args[args.index("--output-a") + 1]).write_bytes(b"a")
        Path(args[args.index("--output-b") + 1]).write_bytes(b"b")
        return b"", b"", 0

    monkeypatch.setattr(
        vs_mod.VocalSeparator, "_run_subprocess", staticmethod(fake_run)
    )
    sep = VocalSeparator(config=cfg)
    await sep.split_duet_vocals(_make_input(tmp_path))

    args = captured["args"]
    q_a = args[args.index("--query-a") + 1]
    q_b = args[args.index("--query-b") + 1]
    assert q_a == "the lead vocal"
    assert q_b == "the second vocal singing a different melody"


@pytest.mark.asyncio
async def test_audiosep_wrapper_missing_raises(tmp_path, monkeypatch):
    cfg = _make_config(tmp_path)
    (tmp_path / "engines" / "AudioSep").mkdir(parents=True)
    monkeypatch.setattr(
        vs_mod, "_AUDIODEP_RUNNER", tmp_path / "no_such_runner.py"
    )
    sep = VocalSeparator(config=cfg)
    with pytest.raises(SeparationError, match="wrapper"):
        await sep.split_duet_vocals(_make_input(tmp_path))
