"""
双人合唱流水线服务（change-id: enhance-cover-pitch-analysis-duet Task 3）

模式对齐 song_pipeline（异步任务 + 阶段状态机），按 Task 3 契约实现为
模块级注册表形态：

状态机：separate → split → analyze → svc_a → svc_b → mix → done / failed

- 提交（create_duet_task）立即返回 task_id，后台 asyncio.create_task 执行流水线；
  阻塞步骤（音频分析 / SVC 推理 / 文件复制 / 混音）以 asyncio.to_thread 包裹。
- 任务状态内存注册表 _duet_tasks（task_id → 状态 dict）+ _duet_lock 保护注册；
  服务重启后任务态不恢复（与 song_pipeline 的磁盘 metadata 恢复不同，Task 3
  契约为内存注册表形态，重启丢态在 GET /duet/{task_id} 表现为 404）。
- 阶段实现：
  1. separate：VocalSeparator.separate_vocal_accompaniment（demucs 人声/伴奏）
  2. split   ：VocalSeparator.split_duet_vocals（AudioSep 文本查询拆两路）
  3. analyze ：各路 analyze_pitch 拿基准 midi；transpose 决策优先级：
     显式 transpose_* > auto_transpose 画像对齐（get_profile，clamp ±12）> 回退 0；
     模型为空 = 该路保留原声，transpose 不生效（结果注明）
  4. svc_a/svc_b：模型非空 → SoVITSSVCInferer（输出目录注入 data/duet/<task_id>/，
     allowed_audio_root 取 data/ 根——单根同时覆盖 duet 产物目录与 data/input
     上传落盘点，沿 song_pipeline 白名单先例；inferer 仅支持单根故取公共祖先）；
     模型空 → skipped 保留原声
  5. mix：mix_tracks 三轨加权混音 → final.wav
- 分离产物复制进任务目录 data/duet/<task_id>/（自包含：vocals/accompaniment/
  part_a/part_b/两路变声/final.wav），经 /api/audio-files/duet/<task_id>/final.wav 播放。
- 任一阶段异常 → 任务 failed，error 含阶段名与原因（SeparationError 含引擎指引透传）。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import math
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from workstation.config import get_settings
from workstation.music.mixer import mix_tracks
from workstation.services.sovits_svc_infer import SoVITSSVCInferer
from workstation.services.vocal_analysis import analyze_pitch
from workstation.services.vocal_separator import VocalSeparator

# 并行契约（Task 2 voice_profile_store，冻结签名 get_profile(speaker_name) -> Optional[dict]，
# 画像 dict 含 f0_median_midi；无画像返回 None）。
# Task 2 落地前本模块可导入（ImportError 兜底为 None → 画像不可得 → transpose 回退 0），
# 集成归 Task 5；单测经模块属性 monkeypatch 注入。
try:
    from workstation.services.voice_profile_store import get_profile
except ImportError:  # pragma: no cover - Task 2 未合流时的开发期兜底
    get_profile = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# VWS 根目录（workstation/services/duet_pipeline.py → 上两级，与 vocal_separator 同锚定）
_VWS_ROOT = Path(__file__).resolve().parents[2]

# 双人合唱产物根目录（config 禁改，模块内锚定；audio-files duet 类别映射此目录）
DUET_DIR = _VWS_ROOT / "data" / "duet"

# SVC 推理输入白名单根：取 data/ 公共祖先根，同时覆盖 duet 产物目录
# （data/duet/<task_id>/）与上传落盘点（data/input）——inferer 仅支持单根，
# 沿 song_pipeline allowed_audio_root 白名单先例取覆盖二者的目录根。
_AUDIO_ALLOWED_ROOT = _VWS_ROOT / "data"

# 流水线阶段（有序）；任务元数据中的 stages 与之一一对应
DUET_STAGES: tuple[str, ...] = ("separate", "split", "analyze", "svc_a", "svc_b", "mix")

# 各阶段进度区间（开始时取下界，完成后取上界）；全部完成时 progress=1.0
_STAGE_PROGRESS: dict[str, tuple[float, float]] = {
    "separate": (0.0, 0.2),
    "split": (0.2, 0.35),
    "analyze": (0.35, 0.5),
    "svc_a": (0.5, 0.65),
    "svc_b": (0.65, 0.8),
    "mix": (0.8, 0.95),
}

# 混音默认增益（与 spec「gain_a/gain_b/accompaniment_gain 默认 1.0/1.0/0.8」一致）
DEFAULT_GAIN_A = 1.0
DEFAULT_GAIN_B = 1.0
DEFAULT_ACCOMPANIMENT_GAIN = 0.8

# 自动 transpose 钳制（半音），与 spec「clamp(±12)」一致
_TRANSPOSE_CLAMP = 12

# AudioSep 默认文本查询（与 VocalSeparator.split_duet_vocals 默认一致）
_DEFAULT_QUERY_A = "the lead vocal"
_DEFAULT_QUERY_B = "the second vocal singing a different melody"

# task_id 合法性（防路径穿越；当前生成为 uuid4 hex）
_DUET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# ---------------------------------------------------------------------------
# 任务注册表（模块级；_duet_lock 仅保护同步注册表读写临界区，不跨 await 持有——
# 进度状态更新在事件循环单线程内完成，无需加锁）
# ---------------------------------------------------------------------------
_duet_tasks: dict[str, dict] = {}
_duet_lock = threading.Lock()
_duet_bg_tasks: dict[str, "asyncio.Task[None]"] = {}


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级），用于任务的创建/完成时间。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_params(params: dict) -> dict:
    """提交参数校验与规范化；非法即抛 ValueError（可读原因）。

    规则（Task 3 契约）：audio_path 必填且文件存在；model_a/model_b 可空
    （空=该路保留原声）；transpose_a/transpose_b 可空（显式值覆盖自动推荐）；
    auto_transpose 默认 true；gains 默认 1.0/1.0/0.8 且必须为 ≥0 有限数值。
    """
    if not isinstance(params, dict):
        raise ValueError("duet 参数非法: 必须为对象（dict）")

    audio_path = str(params.get("audio_path") or "").strip()
    if not audio_path:
        raise ValueError("audio_path 必填（源音频路径，data/input 上传落盘点）")
    if not Path(audio_path).is_file():
        raise ValueError(f"音频文件不存在: {audio_path}")

    model_a = str(params.get("model_a") or "").strip() or None
    model_b = str(params.get("model_b") or "").strip() or None

    def _transpose(key: str) -> Optional[int]:
        value = params.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} 非法: {value!r}（必须为整数半音数）")

    query_a = str(params.get("query_a") or "").strip() or _DEFAULT_QUERY_A
    query_b = str(params.get("query_b") or "").strip() or _DEFAULT_QUERY_B

    normalized = {
        "audio_path": audio_path,
        "model_a": model_a,
        "model_b": model_b,
        "transpose_a": _transpose("transpose_a"),
        "transpose_b": _transpose("transpose_b"),
        "auto_transpose": True if params.get("auto_transpose") is None else bool(params["auto_transpose"]),
        "query_a": query_a,
        "query_b": query_b,
    }
    for key, default in (
        ("gain_a", DEFAULT_GAIN_A),
        ("gain_b", DEFAULT_GAIN_B),
        ("accompaniment_gain", DEFAULT_ACCOMPANIMENT_GAIN),
    ):
        value = params.get(key)
        if value is None:
            value = default
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(f"{key} 非法: {value!r}（必须为 ≥0 的有限数值）")
        normalized[key] = float(value)
    return normalized


# ---------------------------------------------------------------------------
# 提交与查询（公开接口）
# ---------------------------------------------------------------------------


async def create_duet_task(params: dict) -> str:
    """
    提交双人合唱任务，立即返回 task_id，后台执行六阶段流水线。

    Args:
        params: 提交参数 dict（audio_path 必填，其余见 _normalize_params）

    Returns:
        task_id（uuid4 hex，同时作为 data/duet/ 下的子目录名）

    Raises:
        ValueError: 参数非法（缺 audio_path / 文件不存在 / 增益或 transpose 非法）
    """
    normalized = _normalize_params(params)

    task_id = uuid.uuid4().hex
    record: dict = {
        "task_id": task_id,
        "created_at": _now_iso(),
        "status": "pending",  # pending / running / completed / failed
        "stage": "pending",  # pending / separate / split / analyze / svc_a / svc_b / mix / done
        "progress": 0.0,
        "stages": {name: "pending" for name in DUET_STAGES},
        # 实际采用的 transpose：source = auto | explicit | fallback（整体口径，
        # 任一路 explicit 即整体 explicit；分路口径见 source_a/source_b）
        "transposes": {
            "a": 0,
            "b": 0,
            "source": "fallback",
            "source_a": "fallback",
            "source_b": "fallback",
            "notes": [],
        },
        "analysis": {},  # {"a": profile_dict, "b": profile_dict}（analyze 阶段填充）
        "notes": [],  # 跳过说明 / 画像回退说明 / 无模型注记
        "error": None,
        "finished_at": None,
        "params": normalized,
        "files": {},
        "audio_url": None,
    }
    with _duet_lock:
        _duet_tasks[task_id] = record

    task_dir = DUET_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    bg = asyncio.get_running_loop().create_task(_run_duet_pipeline(record))
    _duet_bg_tasks[task_id] = bg
    bg.add_done_callback(lambda t, tid=task_id: _on_bg_done(tid, t))
    logger.info(
        "双人合唱任务已提交: task_id=%s audio=%s model_a=%r model_b=%r auto_transpose=%s",
        task_id,
        normalized["audio_path"],
        normalized["model_a"],
        normalized["model_b"],
        normalized["auto_transpose"],
    )
    return task_id


def get_duet_task(task_id: str) -> Optional[dict]:
    """
    查询任务状态（内存注册表）。

    Returns:
        任务状态 dict 的深拷贝；task_id 非法或不存在时返回 None
    """
    if not isinstance(task_id, str) or not _DUET_ID_PATTERN.match(task_id):
        return None
    with _duet_lock:
        record = _duet_tasks.get(task_id)
    if record is not None:
        return copy.deepcopy(record)
    return None


# ---------------------------------------------------------------------------
# 流水线主流程
# ---------------------------------------------------------------------------


async def _run_duet_pipeline(record: dict) -> None:
    task_id = record["task_id"]
    task_dir = DUET_DIR / task_id
    params = record["params"]
    try:
        record["status"] = "running"

        # 1. separate：demucs 人声/伴奏分离
        _begin_stage(record, "separate")
        separator = VocalSeparator()
        vocals_raw, accompaniment_raw = await separator.separate_vocal_accompaniment(
            params["audio_path"]
        )
        vocals_path = await asyncio.to_thread(
            shutil.copyfile, vocals_raw, task_dir / "vocals.wav"
        )
        accompaniment_path = await asyncio.to_thread(
            shutil.copyfile, accompaniment_raw, task_dir / "accompaniment.wav"
        )
        record["files"]["vocals"] = vocals_path.name
        record["files"]["accompaniment"] = accompaniment_path.name
        _end_stage(record, "separate")

        # 2. split：AudioSep 文本查询拆两路人声
        _begin_stage(record, "split")
        part_a_raw, part_b_raw = await separator.split_duet_vocals(
            vocals_path, params["query_a"], params["query_b"]
        )
        part_a_path = await asyncio.to_thread(
            shutil.copyfile, part_a_raw, task_dir / "part_a.wav"
        )
        part_b_path = await asyncio.to_thread(
            shutil.copyfile, part_b_raw, task_dir / "part_b.wav"
        )
        record["files"]["part_a"] = part_a_path.name
        record["files"]["part_b"] = part_b_path.name
        _end_stage(record, "split")

        # 3. analyze：各路 F0 分析（拿到 part 基准 midi）+ transpose 决策
        _begin_stage(record, "analyze")
        f0_confidence = get_settings().cover_analysis.f0_confidence
        profile_a = await asyncio.to_thread(
            analyze_pitch, str(part_a_path), f0_confidence
        )
        profile_b = await asyncio.to_thread(
            analyze_pitch, str(part_b_path), f0_confidence
        )
        record["analysis"] = {"a": profile_a.to_dict(), "b": profile_b.to_dict()}
        await _determine_transposes(record)
        _end_stage(record, "analyze")

        # 4. svc_a / svc_b：模型非空 → 变声；空 → 跳过保留原声
        part_a_final = await _run_part_svc(
            record, task_dir, "a", part_a_path, record["transposes"]["a"]
        )
        part_b_final = await _run_part_svc(
            record, task_dir, "b", part_b_path, record["transposes"]["b"]
        )

        # 5. mix：part_a + part_b + 伴奏 三轨加权混音 → final.wav
        _begin_stage(record, "mix")
        final_path = task_dir / "final.wav"
        await asyncio.to_thread(
            mix_tracks,
            [
                (str(part_a_final), params["gain_a"]),
                (str(part_b_final), params["gain_b"]),
                (str(accompaniment_path), params["accompaniment_gain"]),
            ],
            str(final_path),
        )
        record["files"]["final"] = final_path.name
        _end_stage(record, "mix")

        record["status"] = "completed"
        record["stage"] = "done"
        record["progress"] = 1.0
        record["finished_at"] = _now_iso()
        record["audio_url"] = f"/api/audio-files/duet/{task_id}/final.wav"
        logger.info(
            "双人合唱流水线完成: task_id=%s transposes=%s final=%s",
            task_id,
            {k: record["transposes"][k] for k in ("a", "b")},
            final_path,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = f"[{record['stage']}] {exc}"
        record["finished_at"] = _now_iso()
        _fail_current_stage(record)
        logger.error(
            "双人合唱流水线失败: task_id=%s stage=%s error=%s",
            task_id,
            record["stage"],
            exc,
        )


async def _determine_transposes(record: dict) -> None:
    """transpose 决策（analyze 阶段内，基于已填充的 analysis）。

    每路优先级：显式 transpose_*（source=explicit）
              > auto_transpose 且画像可得（source=auto，clamp(round(源-目标), ±12)）
              > 回退 0（source=fallback，注记「画像不可得，transpose=0」）。
    模型为空的路径 transpose 不生效（0），结果注记保留原声。
    """
    params = record["params"]
    analysis = record["analysis"]
    transposes = record["transposes"]
    notes = transposes["notes"]

    for part in ("a", "b"):
        model = params[f"model_{part}"]
        explicit = params[f"transpose_{part}"]
        label = part.upper()

        if model is None:
            # 简化契约：无模型则不做变调，transpose 仅在有模型时生效
            transposes[part] = 0
            transposes[f"source_{part}"] = "fallback"
            notes.append(f"{label} 声部未指定模型，保留原声，transpose 不生效")
            continue

        if explicit is not None:
            transposes[part] = int(explicit)
            transposes[f"source_{part}"] = "explicit"
            continue

        if not params["auto_transpose"]:
            transposes[part] = 0
            transposes[f"source_{part}"] = "fallback"
            continue

        target_median: Optional[float] = None
        if get_profile is not None:
            try:
                # 画像计算含数据集扫描/MD5（Task 2 实现，可能为慢操作）→ 线程池执行
                profile = await asyncio.to_thread(get_profile, model)
            except Exception as exc:  # noqa: BLE001 - 画像计算失败不阻断流水线
                notes.append(f"{label} 声部画像计算失败（{exc}），transpose=0")
                profile = None
            if profile:
                try:
                    target_median = float(profile["f0_median_midi"])
                except (KeyError, TypeError, ValueError):
                    notes.append(
                        f"{label} 声部画像缺少 f0_median_midi，transpose=0"
                    )
                    target_median = None
        if target_median is None:
            transposes[part] = 0
            transposes[f"source_{part}"] = "fallback"
            notes.append(f"{label} 声部画像不可得，transpose=0")
            continue

        part_median = float(analysis[part]["f0_median_midi"])
        raw = round(part_median - target_median)
        transposes[part] = int(min(max(raw, -_TRANSPOSE_CLAMP), _TRANSPOSE_CLAMP))
        transposes[f"source_{part}"] = "auto"

    sources = [transposes["source_a"], transposes["source_b"]]
    transposes["source"] = (
        "explicit" if "explicit" in sources else ("auto" if "auto" in sources else "fallback")
    )


async def _run_part_svc(
    record: dict, task_dir: Path, part: str, part_path: Path, transpose: int
) -> Path:
    """
    单路 SVC 变声步骤：复用 SoVITSSVCInferer，返回参与混音的最终 WAV。

    - 模型为空 → skipped（保留原声，不 transpose，注记进 notes）；
    - 输出目录注入 data/duet/<task_id>/（产物自包含，audio-files duet 类别可达）；
    - allowed_audio_root 注入 data/ 根（覆盖 duet 产物目录与 data/input 白名单先例）；
    - 推理产物改名为 part_<part>_converted.wav（converted_<stem>_<uuid> 为 inferer
      内部命名，移动归位后 tasks files 记录规范名）。
    """
    stage = f"svc_{part}"
    model = record["params"][f"model_{part}"]
    label = part.upper()
    if not model:
        _skip_stage(record, stage, f"{label} 声部未指定模型，保留原声")
        # 原声直接作为该路参与混音的产物（part_*_converted = 该路混音输入的规范名）
        record["files"][f"part_{part}_converted"] = part_path.name
        return part_path

    _begin_stage(record, stage)
    svc_cfg = get_settings().sovits_svc
    inferer = SoVITSSVCInferer(
        model_path=model,
        output_dir=str(task_dir),
        models_dir=svc_cfg.models_dir,
        so_vits_svc_dir=svc_cfg.so_vits_svc_dir,
        python_path=svc_cfg.python_path,
        allowed_audio_root=str(_AUDIO_ALLOWED_ROOT),
    )
    converted = await inferer.infer(
        audio_path=str(part_path),
        speaker_id=0,
        transpose=transpose,
        model_path=model,
    )
    final_part = task_dir / f"part_{part}_converted.wav"
    converted_path = Path(converted)
    if converted_path.resolve() != final_part.resolve():
        await asyncio.to_thread(shutil.move, str(converted_path), str(final_part))
    record["files"][f"part_{part}_converted"] = final_part.name
    _end_stage(record, stage)
    logger.info(
        "SVC 变声完成: task_id=%s part=%s model=%s transpose=%s -> %s",
        record["task_id"],
        part,
        model,
        transpose,
        final_part,
    )
    return final_part


# ---------------------------------------------------------------------------
# 阶段状态迁移（内存注册表内直接更新；事件循环单线程，无 await 间隙竞争）
# ---------------------------------------------------------------------------


def _begin_stage(record: dict, name: str) -> None:
    record["stages"][name] = "running"
    record["stage"] = name
    record["progress"] = _STAGE_PROGRESS[name][0]


def _end_stage(record: dict, name: str) -> None:
    record["stages"][name] = "completed"
    record["progress"] = _STAGE_PROGRESS[name][1]


def _skip_stage(record: dict, name: str, message: str) -> None:
    record["stages"][name] = "skipped"
    record["progress"] = _STAGE_PROGRESS[name][1]
    record["notes"].append(message)


def _fail_current_stage(record: dict) -> None:
    for name in DUET_STAGES:
        if record["stages"][name] == "running":
            record["stages"][name] = "failed"
            return


def _on_bg_done(task_id: str, task: "asyncio.Task[None]") -> None:
    """后台任务收尾：弹出注册；未捕获异常在此显式读取，避免 event loop 告警。"""
    _duet_bg_tasks.pop(task_id, None)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("双人合唱流水线后台任务未捕获异常: task_id=%s error=%s", task_id, exc)
