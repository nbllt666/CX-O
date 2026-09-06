"""
Task 5「歌曲流水线服务」单元测试

覆盖：
- mock 引擎（singing_engine=mock）+ mock 伴奏（monkeypatch render_accompaniment，
  免 fluidsynth 依赖）端到端：提交歌谱 → 轮询至 completed → final.wav 存在且合法
- 无和弦轨歌谱：流水线自动生成等长静音伴奏（原生路径，无 monkeypatch）
- 失败路径：非法歌谱 → validate 阶段 failed（错误可读）；歌声引擎未部署 → vocal
  阶段 failed；无 soundfont 且含和弦 → accompaniment 阶段 failed
- SVC：未指定模型跳过（skipped）；指定模型推理失败 → failed 且错误可读；
  指定模型成功 → vocal_svc.wav 参与混音，构造参数钉住目录映射约束
- 并发多任务互不干扰（song_id 唯一、各自 metadata 正确）
- Task 1.2 实施注记：SoVITSSVCInferer 落盘目录与 svc-results 类别映射目录一致
"""
from __future__ import annotations

import asyncio
import json
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

from workstation.config import WorkstationSettings, get_settings  # noqa: E402
from workstation.services.song_pipeline import (  # noqa: E402
    PIPELINE_STAGES,
    SongPipelineService,
)
import workstation.services.song_pipeline as pipeline_module  # noqa: E402

# ---------------------------------------------------------------------------
# 测试辅助
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path, **music_overrides) -> WorkstationSettings:
    """构造隔离的 WorkstationSettings：songs / svc 输出全部落 tmp_path"""
    settings = WorkstationSettings()
    settings.music.songs_dir = str(tmp_path / "songs")
    settings.music.singing_engine = "mock"
    settings.music.soundfont_path = ""
    settings.sovits_svc.infer_output_dir = str(tmp_path / "svc_results")
    settings.sovits_svc.so_vits_svc_dir = str(tmp_path / "so-vits-svc")
    for key, value in music_overrides.items():
        setattr(settings.music, key, value)
    return settings


def _valid_score(**overrides) -> dict:
    """一份合法歌谱：2 音符共 2 拍 @120BPM（1 秒音频，测试快速）+ 1 个和弦"""
    score = {
        "title": "流水线测试",
        "bpm": 120,
        "melody": [
            {"pitch": "C4", "beats": 1.0, "lyric": "你"},
            {"pitch": "E4", "beats": 1.0, "lyric": "好"},
        ],
        "chords": [{"chord": "C", "beats": 2}],
    }
    score.update(overrides)
    return score


def _score_seconds(score: dict) -> float:
    return sum(n["beats"] for n in score["melody"]) * 60.0 / score["bpm"]


def _write_tone(path: Path, seconds: float, freq: float = 110.0, rate: int = 44100) -> Path:
    """写确定性正弦 WAV（16bit 单声道），作为假伴奏/假 SVC 输出"""
    n = max(1, int(round(seconds * rate)))
    scale = 0.2 * 32767.0
    step = 2.0 * math.pi * freq / rate
    pcm = struct.pack(f"<{n}h", *(int(scale * math.sin(step * i)) for i in range(n)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframesraw(pcm)
    return path


def _wav_info(path: Path) -> tuple[int, int, int, int]:
    """返回 (声道数, 位宽字节, 采样率, 帧数)"""
    with wave.open(str(path), "rb") as wf:
        return (wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes())


async def _wait_done(
    service: SongPipelineService, song_id: str, timeout: float = 15.0
) -> dict:
    """轮询任务直至 completed / failed（测试内事件循环让步驱动后台任务）"""
    deadline = time.monotonic() + timeout
    while True:
        info = service.get_task(song_id)
        assert info is not None, f"任务不存在: {song_id}"
        if info["status"] in ("completed", "failed"):
            return info
        if time.monotonic() > deadline:
            raise TimeoutError(f"任务 {song_id} 未在 {timeout}s 内收敛: {info}")
        await asyncio.sleep(0.02)


def _step(info: dict, name: str) -> dict:
    return info["steps"][PIPELINE_STAGES.index(name)]


def _fake_render_accompaniment(
    score: dict, out_wav_path, *, soundfont_path: str | None = None, **kwargs
) -> str:
    """假伴奏渲染：不依赖 fluidsynth，按歌谱时长写 110Hz 正弦（多轨签名适配）"""
    _write_tone(Path(out_wav_path), _score_seconds(score))
    return str(out_wav_path)


# ---------------------------------------------------------------------------
# 端到端成功路径
# ---------------------------------------------------------------------------


class TestPipelineSuccess:
    @pytest.mark.asyncio
    async def test_end_to_end_completed(self, tmp_path, monkeypatch):
        """mock 引擎 + mock 伴奏端到端：提交 → 轮询至 completed → final.wav 合法"""
        monkeypatch.setattr(
            pipeline_module, "render_accompaniment", _fake_render_accompaniment
        )
        service = SongPipelineService(_make_settings(tmp_path))

        song_id = await service.submit(_valid_score())
        assert song_id and isinstance(song_id, str)

        info = await _wait_done(service, song_id)
        assert info["status"] == "completed", f"任务失败: {info['error']}"
        assert info["stage"] == "done"
        assert info["progress"] == 1.0
        assert info["error"] is None
        assert info["finished_at"] is not None

        # 步骤序列完整：validate/accompaniment/vocal/mix 完成，svc 未指定模型 → skipped
        assert [s["name"] for s in info["steps"]] == list(PIPELINE_STAGES)
        for name in ("validate", "accompaniment", "vocal", "mix"):
            assert _step(info, name)["status"] == "completed"
        svc_step = _step(info, "svc")
        assert svc_step["status"] == "skipped"
        assert "跳过" in svc_step["message"]

        # 成品与中间产物落盘
        song_dir = tmp_path / "songs" / song_id
        final_wav = song_dir / "final.wav"
        assert final_wav.is_file()
        assert (song_dir / "vocal_raw.wav").is_file()
        assert (song_dir / "accompaniment.wav").is_file()
        assert not (song_dir / "vocal_svc.wav").exists()  # svc 跳过则无变声产物

        # final.wav 合法：44.1kHz / 16bit / 单声道，时长 ≥ 歌声时长（spec 场景）
        channels, width, rate, frames = _wav_info(final_wav)
        assert (channels, width, rate) == (1, 2, 44100)
        vocal_frames = _wav_info(song_dir / "vocal_raw.wav")[3]
        assert frames >= vocal_frames > 0

        # audio_url 指向 songs 类别受控路径
        assert info["audio_url"] == f"/api/audio-files/songs/{song_id}/final.wav"

        # metadata.json 落盘内容与内存一致（歌谱快照、参数、文件清单）
        meta = json.loads((song_dir / "metadata.json").read_text(encoding="utf-8"))
        assert meta["song_id"] == song_id
        assert meta["status"] == "completed"
        assert meta["score"]["title"] == "流水线测试"
        assert meta["params"]["vocal_gain"] == 1.0
        assert meta["params"]["accompaniment_gain"] == 0.8
        assert meta["files"]["final"] == "final.wav"

    @pytest.mark.asyncio
    async def test_empty_chords_uses_silence_accompaniment(self, tmp_path):
        """无和弦轨：不依赖 fluidsynth，流水线自动落等长静音伴奏（原生路径）"""
        service = SongPipelineService(_make_settings(tmp_path))
        score = _valid_score(chords=[])

        song_id = await service.submit(score)
        info = await _wait_done(service, song_id)
        assert info["status"] == "completed", f"任务失败: {info['error']}"

        song_dir = tmp_path / "songs" / song_id
        acc = song_dir / "accompaniment.wav"
        assert acc.is_file()
        channels, width, rate, frames = _wav_info(acc)
        assert (channels, width, rate) == (1, 2, 44100)
        # 静音伴奏时长 ≈ 歌谱总时长（容差 2 帧）
        expected = _score_seconds(score) * 44100
        assert abs(frames - expected) <= 2
        # 全零静音
        with wave.open(str(acc), "rb") as wf:
            assert not any(wf.readframes(wf.getnframes()))
        assert (song_dir / "final.wav").is_file()


# ---------------------------------------------------------------------------
# 失败路径
# ---------------------------------------------------------------------------


class TestPipelineFailures:
    @pytest.mark.asyncio
    async def test_invalid_score_fails_at_validate(self, tmp_path):
        """非法歌谱 → validate 阶段 failed，错误逐条可读并含字段定位"""
        service = SongPipelineService(_make_settings(tmp_path))

        # 结构错误（beats<=0）：validate_score 结构校验即拦截
        bad_beats = _valid_score(melody=[{"pitch": "C4", "beats": 0}])
        song_id = await service.submit(bad_beats)
        info = await _wait_done(service, song_id)

        assert info["status"] == "failed"
        assert info["stage"] == "validate"
        assert info["finished_at"] is not None
        # 错误信息可读且含字段定位
        assert "bpm" not in info["error"]
        assert "melody[0].beats" in info["error"]
        # validate 步骤标记 failed，后续步骤保持 pending
        assert _step(info, "validate")["status"] == "failed"
        assert _step(info, "accompaniment")["status"] == "pending"
        # 磁盘 metadata 同步为 failed
        meta = json.loads(
            (tmp_path / "songs" / song_id / "metadata.json").read_text(encoding="utf-8")
        )
        assert meta["status"] == "failed"
        assert meta["stage"] == "validate"
        # 无成品
        assert not (tmp_path / "songs" / song_id / "final.wav").exists()

        # 音高错误（结构合法、pitch 非法）：validate_score 逐音符校验拦截
        bad_pitch = _valid_score(melody=[{"pitch": "H9", "beats": 1.0}])
        song_id2 = await service.submit(bad_pitch)
        info2 = await _wait_done(service, song_id2)
        assert info2["status"] == "failed"
        assert info2["stage"] == "validate"
        assert "melody[0].pitch" in info2["error"]

    @pytest.mark.asyncio
    async def test_missing_bpm_fails_readable(self, tmp_path):
        service = SongPipelineService(_make_settings(tmp_path))
        bad = {"title": "缺bpm", "melody": [{"pitch": "C4", "beats": 1.0}]}
        song_id = await service.submit(bad)
        info = await _wait_done(service, song_id)
        assert info["status"] == "failed"
        assert info["stage"] == "validate"
        assert "bpm" in info["error"]

    @pytest.mark.asyncio
    async def test_vocal_failure_diffsinger_undeployed(self, tmp_path):
        """歌声引擎未部署（diffsinger 幽灵目录 + 无声库）→ vocal 阶段 failed"""
        settings = _make_settings(
            tmp_path,
            singing_engine="diffsinger",
            diffsinger_dir=str(tmp_path / "ghost_diffsinger"),
            diffsinger_python=sys.executable,
            voice_bank="lostbank",
        )
        service = SongPipelineService(settings)
        # 无和弦轨走静音伴奏，确保失败点落在 vocal 而非 accompaniment
        song_id = await service.submit(_valid_score(chords=[]))
        info = await _wait_done(service, song_id)

        assert info["status"] == "failed"
        assert info["stage"] == "vocal"
        assert "DiffSinger" in info["error"]
        assert "lostbank" in info["error"]
        assert _step(info, "accompaniment")["status"] == "completed"
        assert _step(info, "vocal")["status"] == "failed"
        assert not (tmp_path / "songs" / song_id / "final.wav").exists()

    @pytest.mark.asyncio
    async def test_accompaniment_failure_missing_soundfont(self, tmp_path):
        """含和弦但未配置 soundfont → accompaniment 阶段 failed，错误逐项可读"""
        service = SongPipelineService(_make_settings(tmp_path))  # soundfont_path=""
        song_id = await service.submit(_valid_score())
        info = await _wait_done(service, song_id)

        assert info["status"] == "failed"
        assert info["stage"] == "accompaniment"
        assert "SoundFont" in info["error"]
        assert _step(info, "validate")["status"] == "completed"
        assert _step(info, "accompaniment")["status"] == "failed"
        assert _step(info, "vocal")["status"] == "pending"

    @pytest.mark.asyncio
    async def test_invalid_gain_rejected_at_submit(self, tmp_path):
        """增益非法在提交时快速失败（ValueError），不进入后台任务"""
        service = SongPipelineService(_make_settings(tmp_path))
        with pytest.raises(ValueError, match="vocal_gain"):
            await service.submit(_valid_score(), vocal_gain=-1.0)
        with pytest.raises(ValueError, match="accompaniment_gain"):
            await service.submit(_valid_score(), accompaniment_gain=float("nan"))


# ---------------------------------------------------------------------------
# SVC 变声步骤
# ---------------------------------------------------------------------------


class _FakeSVCInferer:
    """假 SoVITSSVCInferer：记录构造参数，infer 按真实命名规则落盘 converted_<stem>.wav"""

    captured_init: list[dict] = []

    def __init__(self, **kwargs):
        type(self).captured_init.append(kwargs)
        self._output_dir = Path(kwargs["output_dir"])

    async def infer(self, audio_path, speaker_id=0, transpose=0, model_path=None, cluster_model_path=None):
        src = Path(audio_path)
        assert src.is_file(), "SVC 输入歌声应存在"
        out = self._output_dir / f"converted_{src.stem}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_tone(out, seconds=1.0, freq=220.0)
        return out


class _FailingSVCInferer:
    def __init__(self, **kwargs):
        pass

    async def infer(self, **kwargs):
        raise RuntimeError("svc boom: 模型加载失败")


class TestSvcStep:
    @pytest.mark.asyncio
    async def test_svc_skipped_without_model(self, tmp_path):
        """未指定模型：svc 步骤 skipped，混音直接使用原始歌声"""
        service = SongPipelineService(_make_settings(tmp_path))
        song_id = await service.submit(_valid_score(chords=[]))
        info = await _wait_done(service, song_id)
        assert info["status"] == "completed"
        assert _step(info, "svc")["status"] == "skipped"
        assert "vocal_svc" not in info["files"]

    @pytest.mark.asyncio
    async def test_svc_success_converts_vocal(self, tmp_path, monkeypatch):
        """指定模型 + 推理成功：产出 vocal_svc.wav 参与混音；构造参数钉住目录约束"""
        import workstation.services.sovits_svc_infer as infer_module

        _FakeSVCInferer.captured_init = []
        monkeypatch.setattr(infer_module, "SoVITSSVCInferer", _FakeSVCInferer)

        settings = _make_settings(tmp_path)
        service = SongPipelineService(settings)
        song_id = await service.submit(
            _valid_score(chords=[]), svc_model="fake_model.pth", transpose=2, speaker_id=1
        )
        info = await _wait_done(service, song_id)
        assert info["status"] == "completed", f"任务失败: {info['error']}"
        assert _step(info, "svc")["status"] == "completed"

        song_dir = tmp_path / "songs" / song_id
        assert (song_dir / "vocal_svc.wav").is_file()
        assert (song_dir / "final.wav").is_file()
        assert info["files"]["vocal_svc"] == "vocal_svc.wav"

        # SVC 推理输出落在 svc-results 受控目录，文件名带 song_id（并发不互覆）
        converted = Path(settings.sovits_svc.infer_output_dir) / f"converted_svc_input_{song_id}.wav"
        assert converted.is_file()
        # 临时输入文件已清理
        assert not (song_dir / f"svc_input_{song_id}.wav").exists()

        # 构造参数：output_dir 与 svc-results 映射目录一致；models_dir 来自 config；allowed_audio_root 为 songs_dir
        init_kwargs = _FakeSVCInferer.captured_init[-1]
        assert init_kwargs["output_dir"] == settings.sovits_svc.infer_output_dir
        assert init_kwargs["models_dir"] == settings.sovits_svc.models_dir
        assert init_kwargs["allowed_audio_root"] == str(
            Path(settings.music.songs_dir).resolve()
        )
        assert init_kwargs["model_path"] == "fake_model.pth"

    @pytest.mark.asyncio
    async def test_svc_failure_marks_task_failed(self, tmp_path, monkeypatch):
        """指定模型但推理失败 → svc 阶段 failed，错误信息可读"""
        import workstation.services.sovits_svc_infer as infer_module

        monkeypatch.setattr(infer_module, "SoVITSSVCInferer", _FailingSVCInferer)

        service = SongPipelineService(_make_settings(tmp_path))
        song_id = await service.submit(_valid_score(chords=[]), svc_model="broken.pth")
        info = await _wait_done(service, song_id)

        assert info["status"] == "failed"
        assert info["stage"] == "svc"
        assert "svc boom" in info["error"]
        assert _step(info, "svc")["status"] == "failed"
        assert _step(info, "mix")["status"] == "pending"
        assert not (tmp_path / "songs" / song_id / "final.wav").exists()


# ---------------------------------------------------------------------------
# 并发与查询接口
# ---------------------------------------------------------------------------


class TestConcurrencyAndQuery:
    @pytest.mark.asyncio
    async def test_concurrent_tasks_isolated(self, tmp_path):
        """并发 3 任务：song_id 唯一、各自目录/metadata/成品互不干扰"""
        service = SongPipelineService(_make_settings(tmp_path))
        titles = [f"并发歌-{i}" for i in range(3)]
        song_ids = await asyncio.gather(
            *(
                service.submit(_valid_score(title=t, chords=[]))
                for t in titles
            )
        )
        assert len(set(song_ids)) == 3

        infos = await asyncio.gather(*(_wait_done(service, sid) for sid in song_ids))
        by_title = {info["title"]: info for info in infos}
        assert set(by_title) == set(titles)
        for title, info in by_title.items():
            assert info["status"] == "completed", f"{title} 失败: {info['error']}"
            meta = json.loads(
                (tmp_path / "songs" / info["song_id"] / "metadata.json").read_text(
                    encoding="utf-8"
                )
            )
            assert meta["title"] == title
            assert meta["score"]["title"] == title
            assert (tmp_path / "songs" / info["song_id"] / "final.wav").is_file()

    @pytest.mark.asyncio
    async def test_get_task_and_list_songs(self, tmp_path):
        """get_task 内存优先；新实例（模拟重启）回退磁盘 metadata；list_songs 扫描落盘"""
        settings = _make_settings(tmp_path)
        service = SongPipelineService(settings)
        song_id = await service.submit(_valid_score(chords=[]))
        info = await _wait_done(service, song_id)
        assert info["status"] == "completed"

        # 内存查询
        assert service.get_task(song_id)["song_id"] == song_id
        # 非法 / 不存在 id
        assert service.get_task("../evil") is None
        assert service.get_task("not-exist-song") is None

        # 新实例（内存为空）→ 磁盘恢复
        restored = SongPipelineService(settings)
        from_disk = restored.get_task(song_id)
        assert from_disk is not None
        assert from_disk["status"] == "completed"
        assert from_disk["score"]["title"] == "流水线测试"

        songs = restored.list_songs()
        assert [s["song_id"] for s in songs] == [song_id]
        assert songs[0]["audio_url"].endswith(f"/songs/{song_id}/final.wav")

    def test_list_songs_skips_broken_metadata(self, tmp_path):
        """损坏的 metadata.json 不影响其他歌曲列出"""
        settings = _make_settings(tmp_path)
        songs_dir = Path(settings.music.songs_dir)
        good = songs_dir / "good-song"
        good.mkdir(parents=True)
        (good / "metadata.json").write_text(
            json.dumps({"song_id": "good-song", "title": "好歌", "status": "completed",
                        "created_at": "2026-07-21T00:00:00+08:00"}),
            encoding="utf-8",
        )
        broken = songs_dir / "broken-song"
        broken.mkdir()
        (broken / "metadata.json").write_text("{not-json", encoding="utf-8")

        service = SongPipelineService(settings)
        songs = service.list_songs()
        assert [s["song_id"] for s in songs] == ["good-song"]


# ---------------------------------------------------------------------------
# Task 1.2 实施注记：audio_files 类别映射与 inferer 落盘目录一致性
# ---------------------------------------------------------------------------


class TestAudioDirMappingConsistency:
    def test_svc_results_mapping_matches_inferer_output_dir(self, tmp_path, monkeypatch):
        """svc-results 类别映射目录 == settings.sovits_svc.infer_output_dir == inferer 落盘目录"""
        settings = get_settings()
        monkeypatch.setattr(settings.sovits_svc, "infer_output_dir", str(tmp_path / "svc_out"))
        monkeypatch.setattr(settings.music, "songs_dir", str(tmp_path / "songs"))

        from workstation.api.audio_files import _category_dirs

        dirs = _category_dirs()
        # svc-results 映射钉住 sovits_svc.infer_output_dir
        assert dirs["svc-results"] == Path(settings.sovits_svc.infer_output_dir)
        # songs 映射钉住 music.songs_dir（流水线成品 final.wav 的可服务性）
        assert dirs["songs"] == Path(settings.music.songs_dir)

        # 流水线以同一 output_dir 构造 inferer → converted_*.wav 落盘目录即被服务目录
        from workstation.services.sovits_svc_infer import SoVITSSVCInferer

        inferer = SoVITSSVCInferer(output_dir=settings.sovits_svc.infer_output_dir)
        assert inferer._output_dir == dirs["svc-results"]
