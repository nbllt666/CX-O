"""
Task 3「双人合唱流水线」单元测试（change-id: enhance-cover-pitch-analysis-duet SubTask 3.4）

全 mock 策略（分离/拆分/inferer/画像全部桩替，免引擎依赖；mix 阶段走真实 mix_tracks）：
- 成功链路：六阶段推进、svc 变声产物参与混音、final.wav 合法、auto transpose 对齐画像
- transpose 决策：画像对齐 clamp(±12) / 画像不可得回退 0（含注记）/ 显式值覆盖 auto /
  auto_transpose=false 回退 0 / 无模型不生效（注记）
- 模型空 → svc 阶段 skipped、inferer 零构造
- 阶段异常 → failed、error 含阶段名（SeparationError 透传引擎指引）
- 参数校验：缺 audio_path / 文件缺失 / 增益非法 → ValueError 且不注册任务
- inferer 构造参数钉住目录映射约束（output_dir=data/duet/<task_id>，
  allowed_audio_root 覆盖 data/duet 与 data/input）
"""
from __future__ import annotations

import asyncio
import array
import math
import os
import struct
import sys
import time
import wave
from pathlib import Path

import pytest

# 项目根目录入 sys.path（与 pyproject pythonpath=["."] 对齐，兼容任意 cwd 运行）
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

import workstation.services.duet_pipeline as duet_mod  # noqa: E402
from workstation.services.duet_pipeline import (  # noqa: E402
    DUET_STAGES,
    create_duet_task,
    get_duet_task,
)
from workstation.services.vocal_analysis import VoiceProfile  # noqa: E402
from workstation.services.vocal_separator import SeparationError  # noqa: E402


# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _make_wav(
    path: Path, frames: int, *, freq: float = 440.0, rate: int = 44100, amplitude: float = 0.2
) -> Path:
    """写确定性正弦 WAV（16bit 单声道），供混音消费的真实产物。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, int(frames))
    step = 2.0 * math.pi * freq / rate
    scale = amplitude * 32767.0
    pcm = struct.pack(f"<{n}h", *(int(scale * math.sin(step * i)) for i in range(n)))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframesraw(pcm)
    return path


def _fake_profile(median_midi: float) -> VoiceProfile:
    """固定中位数的假画像（analyze_pitch 桩返回值）。"""
    return VoiceProfile(
        f0_median_hz=440.0 * (2.0 ** ((median_midi - 69.0) / 12.0)),
        f0_median_midi=median_midi,
        range_low_midi=median_midi - 4.0,
        range_high_midi=median_midi + 4.0,
        range_span_semitones=8.0,
        voiced_ratio=0.9,
    )


def _make_stub_separator(out_dir: Path, calls: list, *, split_error=None, separate_error=None):
    """VocalSeparator 桩：separate/split 产物写真实 WAV 供后续阶段消费。"""

    class _StubSeparator:
        def __init__(self, config=None):
            calls.append(("init",))

        async def separate_vocal_accompaniment(self, audio_path):
            calls.append(("separate", str(audio_path)))
            if separate_error is not None:
                raise separate_error
            vocals = _make_wav(out_dir / "stub_vocals.wav", 400, freq=440.0)
            acc = _make_wav(out_dir / "stub_accompaniment.wav", 600, freq=110.0)
            return vocals, acc

        async def split_duet_vocals(self, vocals_path, query_a, query_b):
            calls.append(("split", str(vocals_path), query_a, query_b))
            if split_error is not None:
                raise split_error
            part_a = _make_wav(out_dir / "stub_part_a.wav", 400, freq=330.0)
            part_b = _make_wav(out_dir / "stub_part_b.wav", 500, freq=220.0)
            return part_a, part_b

    return _StubSeparator


def _make_stub_inferer(constructor_kwargs: list, infer_calls: list):
    """SoVITSSVCInferer 桩：记录构造参数与 infer 调用，产物写真实 WAV。"""

    class _StubInferer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            constructor_kwargs.append(kwargs)

        async def infer(self, audio_path, speaker_id=0, transpose=0, model_path=None,
                        cluster_model_path=None):
            infer_calls.append(
                {
                    "audio_path": str(audio_path),
                    "speaker_id": speaker_id,
                    "transpose": transpose,
                    "model_path": model_path,
                }
            )
            out = Path(self.kwargs["output_dir"]) / f"converted_{Path(audio_path).stem}_stub.wav"
            _make_wav(out, 400, freq=261.0)
            return out

    return _StubInferer


def _patch_analysis(monkeypatch, medians: dict[str, float], analyze_calls: list):
    """analyze_pitch 桩：按文件 stem 返回固定中位数画像（同步函数，to_thread 兼容）。"""

    def fake_analyze_pitch(path, f0_confidence=0.6):
        analyze_calls.append((str(path), f0_confidence))
        return _fake_profile(medians[Path(str(path)).stem])

    monkeypatch.setattr(duet_mod, "analyze_pitch", fake_analyze_pitch)


@pytest.fixture
def duet_env(tmp_path, monkeypatch):
    """隔离环境：产物目录指向 tmp、注册表换新（registry/lock 状态跨测试零残留）。"""
    duet_dir = tmp_path / "duet"
    monkeypatch.setattr(duet_mod, "DUET_DIR", duet_dir)
    monkeypatch.setattr(duet_mod, "_duet_tasks", {})
    monkeypatch.setattr(duet_mod, "_duet_bg_tasks", {})
    return duet_dir


async def _wait_done(task_id: str, timeout: float = 10.0) -> dict:
    """轮询任务直至 completed / failed（测试内事件循环让步驱动后台任务）。"""
    deadline = time.monotonic() + timeout
    while True:
        info = get_duet_task(task_id)
        assert info is not None, f"任务不存在: {task_id}"
        if info["status"] in ("completed", "failed"):
            return info
        if time.monotonic() > deadline:
            raise TimeoutError(f"任务 {task_id} 未在 {timeout}s 内收敛: {info}")
        await asyncio.sleep(0.02)


def _stage(info: dict, name: str) -> str:
    return info["stages"][name]


# ---------------------------------------------------------------------------
# 成功链路
# ---------------------------------------------------------------------------


class TestSuccessChain:
    @pytest.mark.asyncio
    async def test_full_chain_auto_transpose_with_profiles(self, duet_env, tmp_path, monkeypatch):
        """双模型 + auto_transpose：六阶段完成、transpose 对齐各自画像、final.wav 合法"""
        calls: list = []
        constructor_kwargs: list = []
        infer_calls: list = []
        analyze_calls: list = []
        monkeypatch.setattr(
            duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, calls)
        )
        monkeypatch.setattr(
            duet_mod, "SoVITSSVCInferer", _make_stub_inferer(constructor_kwargs, infer_calls)
        )
        _patch_analysis(monkeypatch, {"part_a": 62.0, "part_b": 55.0}, analyze_calls)
        monkeypatch.setattr(
            duet_mod,
            "get_profile",
            lambda speaker: {"f0_median_midi": 60.0 if speaker == "modelA" else 63.0},
        )

        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task(
            {
                "audio_path": str(audio),
                "model_a": "modelA",
                "model_b": "modelB",
                "gain_a": 1.0,
                "gain_b": 0.9,
                "accompaniment_gain": 0.7,
            }
        )
        assert task_id and len(task_id) == 32  # uuid4 hex

        info = await _wait_done(task_id)
        assert info["status"] == "completed", f"任务失败: {info['error']}"
        assert info["stage"] == "done"
        assert info["progress"] == 1.0
        assert info["error"] is None
        assert info["finished_at"] is not None
        assert all(_stage(info, name) == "completed" for name in DUET_STAGES)

        # transpose：a=round(62-60)=+2；b=round(55-63)=-8（均未触 clamp）
        assert info["transposes"]["a"] == 2
        assert info["transposes"]["b"] == -8
        assert info["transposes"]["source"] == "auto"
        assert info["transposes"]["source_a"] == "auto"
        assert info["transposes"]["source_b"] == "auto"

        # analyze：两路均分析，基准 midi 落任务结果
        assert len(analyze_calls) == 2
        assert info["analysis"]["a"]["f0_median_midi"] == 62.0
        assert info["analysis"]["b"]["f0_median_midi"] == 55.0

        # SVC：两路各推理一次，transpose 与画像对齐值一致
        assert [c["transpose"] for c in infer_calls] == [2, -8]
        assert [c["model_path"] for c in infer_calls] == ["modelA", "modelB"]

        # inferer 构造参数钉住目录映射约束：allowed_audio_root = data/ 公共祖先根，
        # 生产语义上同时覆盖 duet 产物目录（data/duet/<task_id>）与 data/input 上传落盘点
        assert len(constructor_kwargs) == 2
        for kwargs in constructor_kwargs:
            assert kwargs["output_dir"] == str(duet_env / task_id)
            allowed = Path(kwargs["allowed_audio_root"]).resolve()
            assert allowed == (duet_mod._VWS_ROOT / "data").resolve()
            assert (duet_mod._VWS_ROOT / "data" / "duet").resolve().is_relative_to(allowed)
            assert (duet_mod._VWS_ROOT / "data" / "input").resolve().is_relative_to(allowed)

        # 分离/拆分调用与查询参数
        assert calls[1][0] == "separate"
        assert calls[2][0] == "split"
        assert calls[2][2] == "the lead vocal"
        assert calls[2][3] == "the second vocal singing a different melody"

        # 产物自包含于任务目录
        task_dir = duet_env / task_id
        for name in ("vocals.wav", "accompaniment.wav", "part_a.wav", "part_b.wav",
                     "part_a_converted.wav", "part_b_converted.wav", "final.wav"):
            assert (task_dir / name).is_file(), f"产物缺失: {name}"
        with wave.open(str(task_dir / "final.wav"), "rb") as wf:
            assert wf.getframerate() == 44100
            assert wf.getnframes() >= 600  # ≥ 最长轨（伴奏 600 帧）
        assert info["files"]["final"] == "final.wav"
        assert info["audio_url"] == f"/api/audio-files/duet/{task_id}/final.wav"

    @pytest.mark.asyncio
    async def test_transpose_clamped_to_12(self, duet_env, tmp_path, monkeypatch):
        """画像差超 ±12 → 钳制到 12"""
        monkeypatch.setattr(duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, []))
        monkeypatch.setattr(
            duet_mod, "SoVITSSVCInferer", _make_stub_inferer([], infer_calls := [])
        )
        _patch_analysis(monkeypatch, {"part_a": 70.0, "part_b": 60.0}, [])
        monkeypatch.setattr(
            duet_mod, "get_profile", lambda speaker: {"f0_median_midi": 40.0}
        )
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task(
            {"audio_path": str(audio), "model_a": "m", "model_b": "m"}
        )
        info = await _wait_done(task_id)
        assert info["status"] == "completed", f"任务失败: {info['error']}"
        assert info["transposes"]["a"] == 12  # raw=30 → clamp
        assert infer_calls[0]["transpose"] == 12

    @pytest.mark.asyncio
    async def test_custom_queries_passthrough(self, duet_env, tmp_path, monkeypatch):
        """query_a/query_b 显式给值透传 AudioSep 拆分阶段"""
        calls: list = []
        monkeypatch.setattr(duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, calls))
        monkeypatch.setattr(duet_mod, "SoVITSSVCInferer", _make_stub_inferer([], []))
        _patch_analysis(monkeypatch, {"part_a": 60.0, "part_b": 60.0}, [])
        monkeypatch.setattr(duet_mod, "get_profile", lambda speaker: {"f0_median_midi": 60.0})
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task(
            {
                "audio_path": str(audio),
                "model_a": "m",
                "model_b": "m",
                "query_a": "female lead",
                "query_b": "male harmony",
            }
        )
        info = await _wait_done(task_id)
        assert info["status"] == "completed"
        assert calls[2][2] == "female lead"
        assert calls[2][3] == "male harmony"


# ---------------------------------------------------------------------------
# transpose 决策分支
# ---------------------------------------------------------------------------


class TestTransposeDecision:
    @pytest.mark.asyncio
    async def test_profile_missing_falls_back_to_zero_with_note(self, duet_env, tmp_path, monkeypatch):
        """画像不可得（get_profile → None）→ transpose=0 + 注记「画像不可得，transpose=0」"""
        monkeypatch.setattr(duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, []))
        monkeypatch.setattr(
            duet_mod, "SoVITSSVCInferer", _make_stub_inferer([], infer_calls := [])
        )
        _patch_analysis(monkeypatch, {"part_a": 62.0, "part_b": 62.0}, [])
        monkeypatch.setattr(duet_mod, "get_profile", lambda speaker: None)
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task(
            {"audio_path": str(audio), "model_a": "m", "model_b": "m"}
        )
        info = await _wait_done(task_id)
        assert info["status"] == "completed"
        assert info["transposes"]["a"] == 0 and info["transposes"]["b"] == 0
        assert info["transposes"]["source"] == "fallback"
        notes_text = " ".join(info["transposes"]["notes"])
        assert "画像不可得，transpose=0" in notes_text
        assert all(c["transpose"] == 0 for c in infer_calls)

    @pytest.mark.asyncio
    async def test_explicit_transpose_overrides_auto(self, duet_env, tmp_path, monkeypatch):
        """显式 transpose_a/transpose_b 覆盖画像推荐（source=explicit）"""
        monkeypatch.setattr(duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, []))
        monkeypatch.setattr(
            duet_mod, "SoVITSSVCInferer", _make_stub_inferer([], infer_calls := [])
        )
        _patch_analysis(monkeypatch, {"part_a": 62.0, "part_b": 55.0}, [])
        monkeypatch.setattr(
            duet_mod, "get_profile", lambda speaker: {"f0_median_midi": 60.0}
        )
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task(
            {
                "audio_path": str(audio),
                "model_a": "m",
                "model_b": "m",
                "transpose_a": 3,
                "transpose_b": -2,
            }
        )
        info = await _wait_done(task_id)
        assert info["status"] == "completed"
        assert info["transposes"]["a"] == 3 and info["transposes"]["b"] == -2
        assert info["transposes"]["source"] == "explicit"
        assert [c["transpose"] for c in infer_calls] == [3, -2]

    @pytest.mark.asyncio
    async def test_auto_transpose_off_without_explicit_falls_back(self, duet_env, tmp_path, monkeypatch):
        """auto_transpose=false 且无显式值 → 回退 0，get_profile 不被调用"""
        monkeypatch.setattr(duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, []))
        monkeypatch.setattr(duet_mod, "SoVITSSVCInferer", _make_stub_inferer([], infer_calls := []))
        _patch_analysis(monkeypatch, {"part_a": 62.0, "part_b": 62.0}, [])

        def _unexpected(speaker):
            raise AssertionError("auto_transpose=false 时不应查询画像")

        monkeypatch.setattr(duet_mod, "get_profile", _unexpected)
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task(
            {"audio_path": str(audio), "model_a": "m", "model_b": "m", "auto_transpose": False}
        )
        info = await _wait_done(task_id)
        assert info["status"] == "completed"
        assert info["transposes"]["source"] == "fallback"
        assert info["transposes"]["a"] == 0
        assert all(c["transpose"] == 0 for c in infer_calls)


# ---------------------------------------------------------------------------
# 模型空 / 单侧保留原声
# ---------------------------------------------------------------------------


class TestEmptyModel:
    @pytest.mark.asyncio
    async def test_no_models_skips_svc_and_keeps_original(self, duet_env, tmp_path, monkeypatch):
        """双模型空：svc_a/svc_b skipped、inferer 零构造、原声参与混音、注记保留原声"""
        monkeypatch.setattr(duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, []))
        monkeypatch.setattr(
            duet_mod, "SoVITSSVCInferer", _make_stub_inferer(constructor_kwargs := [], [])
        )
        # analyze 阶段仍执行（全 mock，免 librosa/pyin 依赖真实产物形态）
        _patch_analysis(monkeypatch, {"part_a": 60.0, "part_b": 60.0}, [])
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task({"audio_path": str(audio)})
        info = await _wait_done(task_id)
        assert info["status"] == "completed"
        assert _stage(info, "svc_a") == "skipped"
        assert _stage(info, "svc_b") == "skipped"
        assert constructor_kwargs == []  # inferer 零构造
        notes_text = " ".join(info["notes"])
        assert "A 声部未指定模型，保留原声" in notes_text
        assert "B 声部未指定模型，保留原声" in notes_text
        transpose_notes = " ".join(info["transposes"]["notes"])
        assert "A 声部未指定模型，保留原声，transpose 不生效" in transpose_notes
        assert "B 声部未指定模型，保留原声，transpose 不生效" in transpose_notes
        # 原声直接参与混音：part_converted 记为原 part 文件名
        assert info["files"]["part_a_converted"] == "part_a.wav"
        # mix 阶段仍完成，final.wav 合法
        assert _stage(info, "mix") == "completed"
        assert (duet_env / task_id / "final.wav").is_file()

    @pytest.mark.asyncio
    async def test_single_side_model_keeps_other_original(self, duet_env, tmp_path, monkeypatch):
        """仅 model_a：A 变声（completed）、B 保留原声（skipped）——spec 单侧场景"""
        monkeypatch.setattr(duet_mod, "VocalSeparator", _make_stub_separator(tmp_path, []))
        monkeypatch.setattr(
            duet_mod, "SoVITSSVCInferer", _make_stub_inferer([], infer_calls := [])
        )
        _patch_analysis(monkeypatch, {"part_a": 62.0, "part_b": 55.0}, [])
        monkeypatch.setattr(duet_mod, "get_profile", lambda speaker: {"f0_median_midi": 60.0})
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task({"audio_path": str(audio), "model_a": "modelA"})
        info = await _wait_done(task_id)
        assert info["status"] == "completed"
        assert _stage(info, "svc_a") == "completed"
        assert _stage(info, "svc_b") == "skipped"
        assert len(infer_calls) == 1 and infer_calls[0]["transpose"] == 2
        assert info["transposes"]["a"] == 2 and info["transposes"]["b"] == 0
        assert (duet_env / task_id / "part_b_converted.wav").is_file() is False
        assert info["files"]["part_b_converted"] == "part_b.wav"
        assert (duet_env / task_id / "final.wav").is_file()


# ---------------------------------------------------------------------------
# 失败路径与参数校验
# ---------------------------------------------------------------------------


class TestFailureAndValidation:
    @pytest.mark.asyncio
    async def test_stage_failure_marks_failed_with_stage_name(self, duet_env, tmp_path, monkeypatch):
        """split 阶段异常 → failed、error 含阶段名 [split]、SeparationError 引擎信息透传"""
        split_error = SeparationError("audiosep", "引擎未就绪，请执行 setup_separation.py --clone")
        monkeypatch.setattr(
            duet_mod,
            "VocalSeparator",
            _make_stub_separator(tmp_path, [], split_error=split_error),
        )
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task({"audio_path": str(audio), "model_a": "m"})
        info = await _wait_done(task_id)
        assert info["status"] == "failed"
        assert info["error"].startswith("[split]")
        assert "audiosep" in info["error"]
        assert "setup_separation.py --clone" in info["error"]
        assert _stage(info, "separate") == "completed"
        assert _stage(info, "split") == "failed"
        assert info["finished_at"] is not None
        assert info["audio_url"] is None

    @pytest.mark.asyncio
    async def test_separate_stage_failure_marks_failed(self, duet_env, tmp_path, monkeypatch):
        """separate 阶段异常 → failed、error 含 [separate]"""
        monkeypatch.setattr(
            duet_mod,
            "VocalSeparator",
            _make_stub_separator(tmp_path, [], separate_error=RuntimeError("mock demucs boom")),
        )
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        task_id = await create_duet_task({"audio_path": str(audio)})
        info = await _wait_done(task_id)
        assert info["status"] == "failed"
        assert info["error"].startswith("[separate]")
        assert "mock demucs boom" in info["error"]
        assert _stage(info, "separate") == "failed"

    @pytest.mark.asyncio
    async def test_invalid_params_raise_and_not_registered(self, duet_env, tmp_path):
        """参数非法 → ValueError（可读）且不注册任务"""
        audio = tmp_path / "input.wav"
        audio.write_bytes(b"RIFFfake")

        for bad_params, match in (
            ({}, "audio_path 必填"),
            ({"audio_path": "  "}, "audio_path 必填"),
            ({"audio_path": str(tmp_path / "missing.wav")}, "音频文件不存在"),
            ({"audio_path": str(audio), "gain_a": -1.0}, "gain_a 非法"),
            ({"audio_path": str(audio), "accompaniment_gain": float("nan")}, "accompaniment_gain 非法"),
            ({"audio_path": str(audio), "transpose_a": "x"}, "transpose_a 非法"),
        ):
            with pytest.raises(ValueError, match=match):
                await create_duet_task(bad_params)
        assert duet_mod._duet_tasks == {}

    @pytest.mark.asyncio
    async def test_get_duet_task_unknown_returns_none(self, duet_env):
        assert get_duet_task("nonexistent") is None
        assert get_duet_task("../traversal") is None
        assert get_duet_task("") is None
