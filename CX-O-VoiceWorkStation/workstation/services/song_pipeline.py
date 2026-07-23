"""
歌曲流水线服务：歌谱 → 伴奏 → 原始歌声 → SVC 变声（可选）→ 混音 → 成品落盘

状态机：validate → accompaniment → vocal → svc → mix → done / failed

- 提交（submit）立即返回 song_id，后台 asyncio.create_task 执行流水线
  （与 sovits_svc_trainer 的 asyncio.create_task 后台监控模式一致）；
  阻塞步骤（fluidsynth 子进程 / 引擎合成 / 混音）以 asyncio.to_thread 包裹，
  不阻塞事件循环。
- 任务状态内存注册表 + 逐步落盘 data/songs/<song_id>/metadata.json，
  服务重启后可从磁盘恢复查询（get_task / list_songs）。
- SVC 变声复用 SoVITSSVCInferer：未指定模型时跳过该步骤（skipped）；
  指定模型但推理失败 → 任务 failed 且错误可读。
  推理输出目录与 /api/audio-files/ 的 svc-results 类别映射目录一致
  （均为 settings.sovits_svc.output_dir，见 Task 1.2 实施注记），
  成品 final.wav 位于 songs 类别受控目录内，可直接通过音频服务访问。
- 并发多任务互不干扰：song_id 为 uuid4 hex，SVC 输入文件命名带 song_id，
  避免多任务同 stem 导致推理输出 converted_<stem>.wav 互相覆盖。
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import os
import re
import shutil
import uuid
import wave
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from workstation.config import WorkstationSettings, get_settings
from workstation.music.accompaniment import render_accompaniment
from workstation.music.mixer import mix_wav
from workstation.music.score import total_beats, validate_score
from workstation.services.singing_engine import create_singing_engine

logger = logging.getLogger(__name__)

# 流水线阶段（有序）；任务元数据中的 steps 与之一一对应
PIPELINE_STAGES: tuple[str, ...] = ("validate", "accompaniment", "vocal", "svc", "mix")

# 各阶段进度区间（开始时取下界，完成后取上界）；全部完成时 progress=1.0
_STAGE_PROGRESS: dict[str, tuple[float, float]] = {
    "validate": (0.0, 0.1),
    "accompaniment": (0.1, 0.35),
    "vocal": (0.35, 0.6),
    "svc": (0.6, 0.8),
    "mix": (0.8, 0.95),
}

# 混音默认增益（与 spec「vocal_gain / accompaniment_gain 默认 1.0 / 0.8」一致）
DEFAULT_VOCAL_GAIN = 1.0
DEFAULT_ACCOMPANIMENT_GAIN = 0.8

# 静音伴奏 / 成品采样率（与 mixer.DEFAULT_SAMPLE_RATE 一致）
_SAMPLE_RATE = 44100

# song_id 合法性（防路径穿越；当前生成为 uuid4 hex，正则兼容历史/外部 id）
_SONG_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# metadata.json 结构版本（前向兼容用）
_METADATA_VERSION = 1


class SongScoreValidationError(ValueError):
    """歌谱校验失败：message 为逐条可读错误拼接（含字段定位）"""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("歌谱校验失败: " + "; ".join(self.errors))


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级），用于 metadata 的创建/完成/步骤时间"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_silence_wav(path: "str | Path", seconds: float, sample_rate: int = _SAMPLE_RATE) -> Path:
    """
    生成指定时长的 16bit 单声道静音 WAV（无和弦轨时的伴奏兜底）。

    空 chords 歌谱不进 fluidsynth（空 MIDI 渲染行为不确定），直接落等长静音，
    由 mixer 以较长者为准补齐，保证 final.wav 时长 ≥ 歌声时长。
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_frames = max(1, int(round(max(0.0, seconds) * sample_rate)))
    chunk = b"\x00\x00" * sample_rate  # 1 秒零样本
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        full, rem = divmod(n_frames, sample_rate)
        for _ in range(full):
            wf.writeframesraw(chunk)
        if rem:
            wf.writeframesraw(b"\x00\x00" * rem)
    return out


@dataclass
class SongTask:
    """歌曲任务记录：内存注册表载体，to_dict() 即 metadata.json 内容"""

    song_id: str
    title: str
    created_at: str
    status: str = "pending"  # pending / running / completed / failed
    stage: str = "pending"  # pending / validate / accompaniment / vocal / svc / mix / done
    progress: float = 0.0
    error: Optional[str] = None
    finished_at: Optional[str] = None
    score_raw: dict = field(default_factory=dict)  # 提交时的原始歌谱
    score: Optional[dict] = None  # validate 通过后的规范化快照
    params: dict = field(default_factory=dict)
    steps: list[dict] = field(default_factory=list)
    files: dict = field(default_factory=dict)
    audio_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "version": _METADATA_VERSION,
            "song_id": self.song_id,
            "title": self.title,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "score": self.score if self.score is not None else self.score_raw,
            "params": self.params,
            "steps": self.steps,
            "files": self.files,
            "audio_url": self.audio_url,
        }


class SongPipelineService:
    """
    歌曲流水线服务：异步任务状态机 + 内存注册表 + 磁盘元数据。

    部署要求与项目整体一致：单 worker 运行（uvicorn --workers 1），
    内存注册表不跨进程共享；磁盘 metadata.json 为恢复与历史查询依据。
    """

    def __init__(self, settings: Optional[WorkstationSettings] = None):
        self._settings = settings if settings is not None else get_settings()
        self._tasks: dict[str, SongTask] = {}
        self._bg_tasks: dict[str, "asyncio.Task[None]"] = {}

    # ------------------------------------------------------------------
    # 提交与查询（公开接口）
    # ------------------------------------------------------------------

    async def submit(
        self,
        score: dict,
        *,
        svc_model: Optional[str] = None,
        speaker_id: int = 0,
        transpose: int = 0,
        vocal_gain: float = DEFAULT_VOCAL_GAIN,
        accompaniment_gain: float = DEFAULT_ACCOMPANIMENT_GAIN,
        voice_bank: str = "",
    ) -> str:
        """
        提交歌曲合成任务，立即返回 song_id，后台执行流水线。

        Args:
            score: 歌谱 dict（合法性由 validate 阶段判定，非法歌谱使任务 failed）
            svc_model: SVC 模型路径；空/None 时跳过 svc 步骤直接使用原始歌声
            speaker_id: SVC 说话人 id
            transpose: SVC 变调（半音数）
            vocal_gain: 歌声增益（≥0）
            accompaniment_gain: 伴奏增益（≥0）
            voice_bank: 声库标识（Mock 引擎忽略；空串表示引擎默认）

        Returns:
            song_id（uuid4 hex，同时作为 data/songs/ 下的子目录名）

        Raises:
            ValueError: 增益等参数非法（歌谱非法不在此抛出，走 validate 阶段 failed）
        """
        for name, value in (("vocal_gain", vocal_gain), ("accompaniment_gain", accompaniment_gain)):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{name} 非法: {value!r}（必须为 ≥0 的有限数值）")

        if not isinstance(score, dict):
            # 非 dict 输入无法 JSON 序列化，包装后由 validate 阶段给出可读错误
            score = {"_raw": str(score)}

        song_id = uuid.uuid4().hex
        record = SongTask(
            song_id=song_id,
            title=str(score.get("title") or "未命名歌曲"),
            created_at=_now_iso(),
            score_raw=copy.deepcopy(score),
            params={
                "svc_model": (svc_model or "").strip(),
                "speaker_id": int(speaker_id),
                "transpose": int(transpose),
                "vocal_gain": float(vocal_gain),
                "accompaniment_gain": float(accompaniment_gain),
                "voice_bank": str(voice_bank or ""),
            },
            steps=[
                {
                    "name": name,
                    "status": "pending",  # pending / running / completed / failed / skipped
                    "error": None,
                    "message": "",
                    "started_at": None,
                    "finished_at": None,
                }
                for name in PIPELINE_STAGES
            ],
        )
        self._tasks[song_id] = record
        self._song_dir(song_id).mkdir(parents=True, exist_ok=True)
        self._write_metadata(record)

        bg = asyncio.get_running_loop().create_task(self._run_pipeline(record))
        self._bg_tasks[song_id] = bg
        bg.add_done_callback(lambda t, sid=song_id: self._on_bg_done(sid, t))
        logger.info("歌曲任务已提交: song_id=%s title=%r", song_id, record.title)
        return song_id

    def get_task(self, song_id: str) -> Optional[dict]:
        """
        查询任务状态：内存注册表优先，未命中回退磁盘 metadata.json（服务重启后恢复）。

        Returns:
            任务元数据 dict；song_id 非法或不存在时返回 None
        """
        if not isinstance(song_id, str) or not _SONG_ID_PATTERN.match(song_id):
            return None
        record = self._tasks.get(song_id)
        if record is not None:
            return copy.deepcopy(record.to_dict())
        return self._read_metadata(self._song_dir(song_id) / "metadata.json")

    def list_songs(self) -> list[dict]:
        """
        列出全部歌曲：扫描 songs_dir 读 metadata.json，内存活跃任务覆盖同名磁盘记录
        （内存状态更新更及时），按创建时间倒序。
        """
        songs: dict[str, dict] = {}
        songs_dir = Path(self._settings.music.songs_dir)
        if songs_dir.is_dir():
            for child in songs_dir.iterdir():
                if not child.is_dir():
                    continue
                meta = self._read_metadata(child / "metadata.json")
                if meta is not None and isinstance(meta.get("song_id"), str):
                    songs[meta["song_id"]] = meta
        for sid, record in self._tasks.items():
            songs[sid] = copy.deepcopy(record.to_dict())
        return sorted(songs.values(), key=lambda m: m.get("created_at", ""), reverse=True)

    # ------------------------------------------------------------------
    # 流水线主流程
    # ------------------------------------------------------------------

    async def _run_pipeline(self, record: SongTask) -> None:
        song_dir = self._song_dir(record.song_id)
        try:
            record.status = "running"

            # 1. validate：歌谱校验 + 规范化（默认值填充）
            self._begin_step(record, "validate")
            ok, errors, normalized = validate_score(record.score_raw)
            if not ok or normalized is None:
                raise SongScoreValidationError(errors)
            record.score = normalized
            record.title = str(normalized.get("title") or record.title)
            self._end_step(record, "validate")

            # 2. accompaniment：和弦轨渲染；无和弦轨时落等长静音兜底
            self._begin_step(record, "accompaniment")
            acc_path = song_dir / "accompaniment.wav"
            if normalized.get("chords"):
                await asyncio.to_thread(
                    render_accompaniment,
                    normalized,
                    self._settings.music.soundfont_path,
                    acc_path,
                )
            else:
                seconds = total_beats(normalized) * 60.0 / float(normalized["bpm"])
                await asyncio.to_thread(_write_silence_wav, acc_path, seconds)
            record.files["accompaniment"] = acc_path.name
            self._end_step(record, "accompaniment")

            # 3. vocal：歌声引擎合成原始歌声
            self._begin_step(record, "vocal")
            engine = create_singing_engine(self._settings.music)
            vocal_raw = song_dir / "vocal_raw.wav"
            await asyncio.to_thread(
                engine.synthesize, normalized, record.params["voice_bank"], vocal_raw
            )
            record.files["vocal_raw"] = vocal_raw.name
            self._end_step(record, "vocal")

            # 4. svc：可选变声；未指定模型时跳过
            vocal_for_mix = vocal_raw
            svc_model = record.params["svc_model"]
            if not svc_model:
                self._skip_step(record, "svc", "未指定 svc 模型，跳过变声")
            else:
                self._begin_step(record, "svc")
                vocal_svc = await self._run_svc(record, song_dir, vocal_raw, svc_model)
                record.files["vocal_svc"] = vocal_svc.name
                vocal_for_mix = vocal_svc
                self._end_step(record, "svc")

            # 5. mix：歌声 + 伴奏 → final.wav
            self._begin_step(record, "mix")
            final_path = song_dir / "final.wav"
            await asyncio.to_thread(
                mix_wav,
                vocal_for_mix,
                acc_path,
                final_path,
                vocal_gain=record.params["vocal_gain"],
                accompaniment_gain=record.params["accompaniment_gain"],
            )
            record.files["final"] = final_path.name
            self._end_step(record, "mix")

            record.status = "completed"
            record.stage = "done"
            record.progress = 1.0
            record.finished_at = _now_iso()
            record.audio_url = f"/api/audio-files/songs/{record.song_id}/final.wav"
            self._write_metadata(record)
            logger.info(
                "歌曲流水线完成: song_id=%s title=%r final=%s",
                record.song_id,
                record.title,
                final_path,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record.status = "failed"
            record.error = f"[{record.stage}] {exc}"
            record.finished_at = _now_iso()
            self._fail_current_step(record, str(exc))
            self._write_metadata(record)
            logger.error(
                "歌曲流水线失败: song_id=%s stage=%s error=%s",
                record.song_id,
                record.stage,
                exc,
            )

    async def _run_svc(
        self, record: SongTask, song_dir: Path, vocal_raw: Path, svc_model: str
    ) -> Path:
        """
        SVC 变声步骤：复用 SoVITSSVCInferer，返回歌曲目录内的 vocal_svc.wav。

        - 推理输出目录 = settings.sovits_svc.output_dir（与 /api/audio-files/ 的
          svc-results 类别映射目录一致，Task 1.2 注记钉住），模型路径校验沿用
          inferer 既有的 output_dir / sovits logs 白名单，不绕过安全约束；
        - allowed_audio_root 传 songs_dir 解析路径，使歌曲目录内的歌声输入
          通过 inferer 的路径校验；
        - 输入文件名带 song_id，避免并发任务同 stem 输出 converted_<stem>.wav
          互相覆盖；推理完成后复制成品回歌曲目录（自包含），临时输入即删。
        """
        from workstation.services.sovits_svc_infer import SoVITSSVCInferer

        svc_cfg = self._settings.sovits_svc
        inferer = SoVITSSVCInferer(
            model_path=svc_model,
            output_dir=svc_cfg.output_dir,
            so_vits_svc_dir=svc_cfg.so_vits_svc_dir,
            python_path=svc_cfg.python_path,
            allowed_audio_root=str(Path(self._settings.music.songs_dir).resolve()),
        )
        svc_input = song_dir / f"svc_input_{record.song_id}.wav"
        await asyncio.to_thread(shutil.copyfile, vocal_raw, svc_input)
        try:
            converted = await inferer.infer(
                audio_path=str(svc_input),
                speaker_id=record.params["speaker_id"],
                transpose=record.params["transpose"],
                model_path=svc_model,
            )
        finally:
            try:
                svc_input.unlink()
            except OSError:
                pass

        vocal_svc = song_dir / "vocal_svc.wav"
        if Path(converted).resolve() != vocal_svc.resolve():
            await asyncio.to_thread(shutil.copyfile, converted, vocal_svc)
        logger.info("SVC 变声完成: song_id=%s model=%s -> %s", record.song_id, svc_model, vocal_svc)
        return vocal_svc

    # ------------------------------------------------------------------
    # 步骤状态与元数据落盘
    # ------------------------------------------------------------------

    def _step(self, record: SongTask, name: str) -> dict:
        return record.steps[PIPELINE_STAGES.index(name)]

    def _begin_step(self, record: SongTask, name: str) -> None:
        step = self._step(record, name)
        step["status"] = "running"
        step["started_at"] = _now_iso()
        record.stage = name
        record.progress = _STAGE_PROGRESS[name][0]
        self._write_metadata(record)

    def _end_step(self, record: SongTask, name: str) -> None:
        step = self._step(record, name)
        step["status"] = "completed"
        step["finished_at"] = _now_iso()
        record.progress = _STAGE_PROGRESS[name][1]
        self._write_metadata(record)

    def _skip_step(self, record: SongTask, name: str, message: str) -> None:
        step = self._step(record, name)
        step["status"] = "skipped"
        step["message"] = message
        step["finished_at"] = _now_iso()
        record.progress = _STAGE_PROGRESS[name][1]
        self._write_metadata(record)

    def _fail_current_step(self, record: SongTask, error: str) -> None:
        for step in record.steps:
            if step["status"] == "running":
                step["status"] = "failed"
                step["error"] = error
                step["finished_at"] = _now_iso()
                return

    def _song_dir(self, song_id: str) -> Path:
        return Path(self._settings.music.songs_dir) / song_id

    def _write_metadata(self, record: SongTask) -> None:
        """原子写 metadata.json（临时文件 + os.replace），每步状态迁移后调用"""
        song_dir = self._song_dir(record.song_id)
        song_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = song_dir / "metadata.json.tmp"
        payload = json.dumps(record.to_dict(), ensure_ascii=False, indent=2, default=str)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, song_dir / "metadata.json")

    @staticmethod
    def _read_metadata(path: Path) -> Optional[dict]:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("读取歌曲元数据失败: %s (%s)", path, exc)
            return None
        return data if isinstance(data, dict) else None

    def _on_bg_done(self, song_id: str, task: "asyncio.Task[None]") -> None:
        """后台任务收尾：弹出注册；未捕获异常在此显式读取，避免 event loop 告警"""
        self._bg_tasks.pop(song_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("歌曲流水线后台任务未捕获异常: song_id=%s error=%s", song_id, exc)


# ---------------------------------------------------------------------------
# 模块级单例（与 api/sovits_svc._get_trainer 的单例模式一致）
# ---------------------------------------------------------------------------

_pipeline_instance: Optional[SongPipelineService] = None


def get_song_pipeline() -> SongPipelineService:
    """获取 SongPipelineService 稳定单例，供 API 路由 / CXFC 插件复用"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = SongPipelineService(get_settings())
    return _pipeline_instance
