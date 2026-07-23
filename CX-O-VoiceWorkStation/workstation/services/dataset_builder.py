"""
VoxCPM 批量数据集构建与 SVC 数据集管理服务

- 批量生成：输入文本清单（每条约 {text, control?}），逐条调用 VoxCPM 生成 WAV，
  落盘为 So-VITS-SVC 训练期望的目录结构：
      data/training/sovits_svc/raw/<speaker_name>/*.wav
  （与 sovits_svc_trainer.preprocess() 的 raw_dir 约定一致，
    即 training_data_dir="data/training/sovits_svc" 时可直接 preprocess）
- MD5 manifest：每个生成文件计算内容 MD5 写入 manifest.json；
  条目指纹（text+mode+control+参数 的 MD5）用于防重复——
  重复提交相同文本+参数时跳过已存在条目，不重复生成。
- 训练数据目录访问统一经 security_utils.validate_training_data_dir() 集中校验，
  本模块不自定义任何训练根目录常量（_DATASETS_REL_DIR 仅为传入校验器的相对子路径）。
- 异步任务模式与 song_pipeline 一致：submit 立即返回 task_id，
  后台 asyncio.create_task 执行，get_task 查询进度（done/total/current_text/failed）。

部署要求与项目整体一致：单 worker 运行（uvicorn --workers 1），
任务注册表为进程内存状态，不跨进程共享。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from workstation.config import WorkstationSettings, get_settings
from workstation.services.security_utils import validate_training_data_dir

logger = logging.getLogger(__name__)

# 数据集根目录（相对路径，仅作为 validate_training_data_dir 的入参；
# 训练根目录的唯一权威定义在 services/security_utils.py）
_DATASETS_REL_DIR = "data/training/sovits_svc/raw"

# manifest.json 结构版本（前向兼容用）
_MANIFEST_VERSION = 1

# 数据集名（speaker 目录名）严格白名单：字母/数字/下划线/连字符，1~64 字符
_DATASET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# 清洗用：不在白名单内的字符替换为下划线（与 sovits_svc_trainer 的 speaker 清洗语义一致）
_SPEAKER_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_-]")

# 允许导入/统计的音频扩展名
AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg")

# 支持的批量数据集生成引擎（SVC 训练数据多来源）
ENGINE_VOXCPM = "voxcpm"
ENGINE_ORPHEUSTTS = "orpheustts"
ENGINE_F5TTS = "f5tts"
_SUPPORTED_ENGINES = (ENGINE_VOXCPM, ENGINE_ORPHEUSTTS, ENGINE_F5TTS)


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级）"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sanitize_speaker_name(name: str) -> str:
    """清洗 speaker_name：非白名单字符替换为下划线（批量提交入口的宽容策略）。

    与 sovits_svc_trainer._sanitize_speaker_name 语义保持一致，
    保证批量生成的目录名与后续 preprocess 的 speaker_name 对齐。
    """
    if not name:
        return "speaker"
    cleaned = _SPEAKER_INVALID_CHARS.sub("_", name.strip())
    cleaned = cleaned.strip("_") or "speaker"
    return cleaned


def ensure_valid_dataset_name(name: str) -> str:
    """严格校验数据集名（导入/删除入口的严格策略）。

    必须整体匹配白名单正则，拒绝路径分隔符、`..` 等穿越尝试。

    Raises:
        ValueError: 名称非法时
    """
    if not name or not _DATASET_NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid dataset name: {name!r}. "
            "Only letters, digits, underscore and hyphen are allowed (1-64 chars), "
            "path separators and '..' are forbidden."
        )
    return name


def resolve_datasets_root() -> Path:
    """解析数据集根目录（data/training/sovits_svc/raw），经集中校验。"""
    return validate_training_data_dir(_DATASETS_REL_DIR)


def resolve_dataset_dir(speaker_name: str) -> Path:
    """解析指定 speaker 的数据集目录，经 validate_training_data_dir 集中校验。

    Args:
        speaker_name: 已清洗或已严格校验的 speaker 目录名

    Returns:
        解析后的数据集目录路径（不保证存在）
    """
    return validate_training_data_dir(f"{_DATASETS_REL_DIR}/{speaker_name}")


def _md5_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """计算文件内容 MD5（分块读取，避免大文件一次性载入内存）"""
    digest = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _entry_fingerprint(params: dict) -> str:
    """条目指纹：params 的稳定 MD5，用于重复提交去重。

    调用方在 params 中按引擎构造去重维度：
    - voxcpm：沿用旧版字段集（text/mode/control/参考音频/参数），不含 engine，
      保持与既有 manifest 的 voxcpm 条目完全兼容（旧 fingerprint 命中跳过）。
    - orpheustts / f5tts：在 params 中带 engine 维度，与 voxcpm 及彼此区分
      （同文本用不同引擎生成视为不同条目，各保留一份）。
    """
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


@dataclass
class BatchDatasetTask:
    """批量数据集任务记录：内存注册表载体，to_dict() 即 API 响应内容"""

    task_id: str
    speaker_name: str
    dataset_dir: str
    total: int
    mode: str
    created_at: str
    engine: str = "voxcpm"  # 引擎来源（voxcpm / orpheustts / f5tts）
    status: str = "pending"  # pending / running / completed / failed
    done: int = 0  # 本次新生成的条数
    skipped: int = 0  # 指纹命中 manifest 跳过的条数
    failed: int = 0  # 生成失败的条数
    current_text: Optional[str] = None
    error: Optional[str] = None
    finished_at: Optional[str] = None
    failures: list[dict] = field(default_factory=list)  # [{index, text, error}]

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "speaker_name": self.speaker_name,
            "dataset_dir": self.dataset_dir,
            "mode": self.mode,
            "engine": self.engine,
            "status": self.status,
            "total": self.total,
            "done": self.done,
            "skipped": self.skipped,
            "failed": self.failed,
            "current_text": self.current_text,
            "error": self.error,
            "failures": list(self.failures),
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class DatasetBuilderService:
    """
    批量数据集构建服务：异步任务 + 内存注册表 + MD5 manifest 防重。

    支持三引擎来源（SVC 训练数据多来源）：
    - voxcpm（默认）：调用 VoxCPMClient，按 mode（design/controllable_clone/ultimate_clone）分发
    - orpheustts：调用 OrpheusClient.synthesize，用预设音色生成（control 字段可覆盖 voice）
    - f5tts：调用 F5TTSClient.synthesize，用参考音频 + ref_text 克隆音色生成
              （reference_audio_path 作 ref_audio，prompt_text 作 ref_text）

    client_factory 可注入自定义客户端工厂（测试用）；
    默认工厂惰性复用各 engine 的单例（get_voxcpm_client / get_orpheus_client / get_f5tts_client）。
    """

    def __init__(
        self,
        settings: Optional[WorkstationSettings] = None,
        client_factory: Optional[Callable[[], Any]] = None,
        orpheus_client_factory: Optional[Callable[[], Any]] = None,
        f5tts_client_factory: Optional[Callable[[], Any]] = None,
    ):
        self._settings = settings if settings is not None else get_settings()
        self._client_factory = client_factory or _default_client_factory
        self._orpheus_client_factory = orpheus_client_factory or _default_orpheus_client_factory
        self._f5tts_client_factory = f5tts_client_factory or _default_f5tts_client_factory
        self._tasks: dict[str, BatchDatasetTask] = {}
        self._bg_tasks: dict[str, "asyncio.Task[None]"] = {}

    # ------------------------------------------------------------------
    # 提交与查询（公开接口）
    # ------------------------------------------------------------------

    async def submit(
        self,
        speaker_name: str,
        texts: list[dict],
        *,
        mode: str = "design",
        engine: str = ENGINE_VOXCPM,
        control: str = "",
        reference_audio_path: Optional[str] = None,
        prompt_audio_path: Optional[str] = None,
        prompt_text: Optional[str] = None,
        cfg_value: Optional[float] = None,
        inference_timesteps: Optional[int] = None,
    ) -> str:
        """
        提交批量数据集生成任务，立即返回 task_id，后台逐条生成。

        Args:
            speaker_name: 目标 speaker（数据集）名，按宽容策略清洗
            texts: 文本清单，每条 {"text": str, "control": Optional[str]}，
                   条目级 control 覆盖任务级 control
            mode: VoxCPM 模式（design / controllable_clone / ultimate_clone）
            control: 任务级控制描述（声音设计/克隆控制文本）
            reference_audio_path: controllable_clone 模式参考音频（服务端受控路径）
            prompt_audio_path / prompt_text: ultimate_clone 模式提示音频与文本
            cfg_value / inference_timesteps: 可选推理参数覆盖

        Returns:
            task_id（uuid4 hex）

        Raises:
            ValueError: texts 为空、模式专属参数缺失或数据集目录校验失败
        """
        if not texts:
            raise ValueError("texts must not be empty")
        for i, item in enumerate(texts):
            text = item.get("text") if isinstance(item, dict) else None
            if not text or not str(text).strip():
                raise ValueError(f"texts[{i}].text must not be empty")

        # engine 校验：仅接受三引擎之一
        if engine not in _SUPPORTED_ENGINES:
            raise ValueError(
                f"Unsupported engine: {engine!r} (allowed: {', '.join(_SUPPORTED_ENGINES)})"
            )

        # mode 专属校验仅在 voxcpm 引擎下生效（orpheustts/f5tts 忽略 mode）
        if engine == ENGINE_VOXCPM:
            if mode == "controllable_clone" and not reference_audio_path:
                raise ValueError("reference_audio_path is required for controllable_clone mode")
            if mode == "ultimate_clone":
                if not prompt_audio_path:
                    raise ValueError("prompt_audio_path is required for ultimate_clone mode")
                if not prompt_text:
                    raise ValueError("prompt_text is required for ultimate_clone mode")

        # f5tts 是声音克隆型 TTS：必须提供参考音频（ref_audio）与参考文本（ref_text）
        # reference_audio_path → ref_audio，prompt_text → ref_text
        if engine == ENGINE_F5TTS:
            if not reference_audio_path:
                raise ValueError("reference_audio_path is required for f5tts engine (as ref_audio)")
            if not prompt_text:
                raise ValueError("prompt_text is required for f5tts engine (as ref_text)")

        speaker = sanitize_speaker_name(speaker_name)
        # 训练数据目录集中校验（拒绝绝对路径/目录穿越）
        dataset_dir = resolve_dataset_dir(speaker)
        dataset_dir.mkdir(parents=True, exist_ok=True)

        task_id = uuid.uuid4().hex
        record = BatchDatasetTask(
            task_id=task_id,
            speaker_name=speaker,
            dataset_dir=str(dataset_dir),
            total=len(texts),
            mode=mode,
            created_at=_now_iso(),
            engine=engine,
        )
        self._tasks[task_id] = record

        bg = asyncio.get_running_loop().create_task(
            self._run(
                record,
                texts,
                control=control,
                reference_audio_path=reference_audio_path,
                prompt_audio_path=prompt_audio_path,
                prompt_text=prompt_text,
                cfg_value=cfg_value,
                inference_timesteps=inference_timesteps,
            )
        )
        self._bg_tasks[task_id] = bg
        bg.add_done_callback(lambda t, tid=task_id: self._on_bg_done(tid, t))
        logger.info(
            "批量数据集任务已提交: task_id=%s speaker=%s total=%d engine=%s mode=%s",
            task_id, speaker, len(texts), engine, mode,
        )
        return task_id

    def get_task(self, task_id: str) -> Optional[dict]:
        """查询任务状态；task_id 不存在时返回 None"""
        record = self._tasks.get(task_id)
        if record is None:
            return None
        return dict(record.to_dict())

    # ------------------------------------------------------------------
    # 批量生成主流程
    # ------------------------------------------------------------------

    async def _run(
        self,
        record: BatchDatasetTask,
        texts: list[dict],
        *,
        control: str,
        reference_audio_path: Optional[str],
        prompt_audio_path: Optional[str],
        prompt_text: Optional[str],
        cfg_value: Optional[float],
        inference_timesteps: Optional[int],
    ) -> None:
        dataset_dir = Path(record.dataset_dir)
        try:
            record.status = "running"
            manifest = self._load_manifest(dataset_dir)
            entries: list[dict] = manifest.setdefault("entries", [])
            by_fingerprint = {e.get("fingerprint"): e for e in entries}

            # 按引擎获取对应 client（各引擎工厂惰性构造）
            engine = record.engine
            if engine == ENGINE_VOXCPM:
                client = self._client_factory()
            elif engine == ENGINE_ORPHEUSTTS:
                client = self._orpheus_client_factory()
            else:  # ENGINE_F5TTS
                client = self._f5tts_client_factory()

            # voxcpm 推理参数覆盖（仅 voxcpm 引擎使用）
            kwargs: dict[str, Any] = {}
            if engine == ENGINE_VOXCPM:
                if cfg_value is not None:
                    kwargs["cfg_value"] = cfg_value
                if inference_timesteps is not None:
                    kwargs["inference_timesteps"] = inference_timesteps

            for index, item in enumerate(texts):
                text = str(item["text"])
                item_control = item.get("control")
                effective_control = control if item_control is None else str(item_control)
                record.current_text = text

                # 各引擎的去重指纹参数（voxcpm 沿用旧字段集保持兼容；orpheus/f5tts 带 engine 维度）
                if engine == ENGINE_VOXCPM:
                    fp_params = {
                        "text": text,
                        "mode": record.mode,
                        "control": effective_control,
                        "reference_audio_path": reference_audio_path,
                        "prompt_audio_path": prompt_audio_path,
                        "prompt_text": prompt_text,
                        "cfg_value": cfg_value,
                        "inference_timesteps": inference_timesteps,
                    }
                elif engine == ENGINE_ORPHEUSTTS:
                    # orpheustts 用预设音色生成；control 字段作为可选 voice 覆盖，空则用配置默认音色
                    voice = effective_control or self._orpheus_default_voice()
                    fp_params = {
                        "engine": ENGINE_ORPHEUSTTS,
                        "text": text,
                        "voice": voice,
                    }
                else:  # ENGINE_F5TTS
                    fp_params = {
                        "engine": ENGINE_F5TTS,
                        "text": text,
                        "reference_audio_path": reference_audio_path,
                        "prompt_text": prompt_text,
                    }
                fingerprint = _entry_fingerprint(fp_params)

                existing = by_fingerprint.get(fingerprint)
                if existing is not None and (dataset_dir / existing["file"]).is_file():
                    # 重复提交：指纹命中且文件仍在，跳过不重复生成
                    record.skipped += 1
                    logger.info("批量数据集跳过重复条目: task_id=%s index=%d file=%s",
                                record.task_id, index, existing["file"])
                    continue

                filename = f"{len(entries) + 1:04d}_{fingerprint[:8]}.wav"
                output_path = dataset_dir / filename
                try:
                    await self._generate_one(
                        engine, client, record.mode, text, effective_control,
                        reference_audio_path, prompt_audio_path, prompt_text,
                        output_path, kwargs,
                    )
                    if not output_path.is_file():
                        raise RuntimeError(f"生成完成但输出文件不存在: {output_path}")
                except Exception as exc:
                    # 单条失败不中断整批：计入 failed 并继续后续条目
                    record.failed += 1
                    record.failures.append({"index": index, "text": text, "error": str(exc)})
                    logger.warning(
                        "批量数据集单条生成失败: task_id=%s index=%d error=%s",
                        record.task_id, index, exc,
                    )
                    continue

                entry = {
                    "fingerprint": fingerprint,
                    "file": filename,
                    "md5": _md5_file(output_path),
                    "text": text,
                    "engine": engine,
                    "mode": record.mode,
                    "control": effective_control,
                    "created_at": _now_iso(),
                }
                if existing is not None:
                    # manifest 有记录但文件丢失：原位替换，重新生成
                    entries[entries.index(existing)] = entry
                else:
                    entries.append(entry)
                by_fingerprint[fingerprint] = entry
                self._write_manifest(dataset_dir, manifest)
                record.done += 1

            record.current_text = None
            record.finished_at = _now_iso()
            if record.failed == 0:
                record.status = "completed"
            else:
                record.status = "failed"
                first = record.failures[0]
                record.error = f"{record.failed}/{record.total} 条生成失败，首条: {first['error']}"
            logger.info(
                "批量数据集任务结束: task_id=%s status=%s done=%d skipped=%d failed=%d",
                record.task_id, record.status, record.done, record.skipped, record.failed,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            record.current_text = None
            record.finished_at = _now_iso()
            logger.error("批量数据集任务失败: task_id=%s error=%s", record.task_id, exc)

    async def _generate_one(
        self,
        engine: str,
        client: Any,
        mode: str,
        text: str,
        control: str,
        reference_audio_path: Optional[str],
        prompt_audio_path: Optional[str],
        prompt_text: Optional[str],
        output_path: Path,
        kwargs: dict,
    ) -> None:
        """按引擎调用对应 client 生成单条音频并落盘到 output_path；失败抛异常由上层按条捕获。

        - voxcpm：按 mode（design/controllable_clone/ultimate_clone）调用 VoxCPMClient，
          由 client 直接写 output_path
        - orpheustts：调用 OrpheusClient.synthesize(text, voice) 返回 WAV bytes，落盘 output_path
          （voice 取 control，空则用配置默认音色）
        - f5tts：调用 F5TTSClient.synthesize(text, ref_audio_path, ref_text) 返回 WAV bytes，落盘 output_path
          （ref_audio=reference_audio_path, ref_text=prompt_text）
        """
        if engine == ENGINE_VOXCPM:
            if mode == "design":
                await client.design(text=text, control=control, output_path=str(output_path), **kwargs)
            elif mode == "controllable_clone":
                await client.controllable_clone(
                    text=text, control=control,
                    reference_audio=reference_audio_path,
                    output_path=str(output_path), **kwargs,
                )
            elif mode == "ultimate_clone":
                await client.ultimate_clone(
                    text=text, prompt_audio=prompt_audio_path, prompt_text=prompt_text,
                    output_path=str(output_path), **kwargs,
                )
            else:
                raise ValueError(f"Unsupported VoxCPM mode: {mode!r}")
        elif engine == ENGINE_ORPHEUSTTS:
            voice = control or self._orpheus_default_voice()
            wav_bytes = await client.synthesize(text=text, voice=voice)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(wav_bytes)
        elif engine == ENGINE_F5TTS:
            wav_bytes = await client.synthesize(
                text=text,
                ref_audio_path=reference_audio_path,
                ref_text=prompt_text,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(wav_bytes)
        else:
            raise ValueError(f"Unsupported engine: {engine!r}")

    def _orpheus_default_voice(self) -> str:
        """读取 OrpheusConfig 默认音色（orpheustts 引擎在 control 为空时使用）。"""
        return self._settings.orpheus.voice

    # ------------------------------------------------------------------
    # manifest 读写
    # ------------------------------------------------------------------

    def _load_manifest(self, dataset_dir: Path) -> dict:
        """读取 manifest.json；不存在时新建骨架，损坏时告警并按空清单处理"""
        path = dataset_dir / "manifest.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    return data
                logger.warning("manifest.json 结构异常，按空清单处理: %s", path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("读取 manifest.json 失败，按空清单处理: %s (%s)", path, exc)
        return {"version": _MANIFEST_VERSION, "entries": []}

    def _write_manifest(self, dataset_dir: Path, manifest: dict) -> None:
        """原子写 manifest.json（临时文件 + os.replace），每条生成成功后调用"""
        tmp_path = dataset_dir / "manifest.json.tmp"
        payload = json.dumps(manifest, ensure_ascii=False, indent=2)
        tmp_path.write_text(payload, encoding="utf-8")
        os.replace(tmp_path, dataset_dir / "manifest.json")

    def _on_bg_done(self, task_id: str, task: "asyncio.Task[None]") -> None:
        """后台任务收尾：弹出注册；未捕获异常在此显式读取，避免 event loop 告警"""
        self._bg_tasks.pop(task_id, None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("批量数据集后台任务未捕获异常: task_id=%s error=%s", task_id, exc)


def _default_client_factory():
    """默认 VoxCPM 客户端工厂：惰性查找 get_voxcpm_client，支持测试 monkeypatch"""
    from workstation.services.voxcpm_client import get_voxcpm_client

    return get_voxcpm_client(config=get_settings().voxcpm)


def _default_orpheus_client_factory():
    """默认 Orpheus 客户端工厂：惰性查找 get_orpheus_client，支持测试 monkeypatch"""
    from workstation.services.orpheus_client import get_orpheus_client

    settings = get_settings()
    return get_orpheus_client(
        url=settings.orpheus.url,
        voice=settings.orpheus.voice,
        timeout=settings.orpheus.timeout,
    )


def _default_f5tts_client_factory():
    """默认 F5-TTS 客户端工厂：惰性查找 get_f5tts_client，支持测试 monkeypatch"""
    from workstation.services.f5tts_client import get_f5tts_client

    settings = get_settings()
    return get_f5tts_client(
        url=settings.f5tts.server_url,
        timeout=settings.f5tts.timeout,
    )


# ---------------------------------------------------------------------------
# 数据集管理（列表 / 导入落盘 / 删除），供 API 层调用
# ---------------------------------------------------------------------------


def list_datasets() -> list[dict]:
    """列出全部数据集：扫描数据集根目录下的 speaker 子目录。

    Returns:
        [{name, file_count, total_size_bytes, created_at, has_manifest}]，按名称升序
    """
    root = resolve_datasets_root()
    datasets: list[dict] = []
    if not root.is_dir():
        return datasets
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        audio_files = [
            f for f in child.iterdir()
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
        total_size = sum(f.stat().st_size for f in audio_files)
        datasets.append(
            {
                "name": child.name,
                "file_count": len(audio_files),
                "total_size_bytes": total_size,
                "created_at": datetime.fromtimestamp(child.stat().st_ctime)
                .astimezone()
                .isoformat(timespec="seconds"),
                "has_manifest": (child / "manifest.json").is_file(),
            }
        )
    return datasets


def delete_dataset(name: str) -> Path:
    """删除指定数据集目录（严格名称校验 + 存在性检查 + 集中路径校验）。

    Raises:
        ValueError: 名称非法（含路径穿越尝试）时
        FileNotFoundError: 数据集不存在时
    """
    import shutil

    valid_name = ensure_valid_dataset_name(name)
    dataset_dir = resolve_dataset_dir(valid_name)
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Dataset not found: {valid_name}")
    shutil.rmtree(dataset_dir)
    logger.info("数据集已删除: %s", dataset_dir)
    return dataset_dir


def save_import_file(dataset_dir: Path, filename: str, data: bytes) -> Path:
    """将导入的单个音频文件落盘到数据集目录。

    文件名仅取 basename（剥离客户端路径），扩展名须在音频白名单内。

    Raises:
        ValueError: 文件名非法或扩展名不在白名单时
    """
    base = os.path.basename(filename or "")
    if not base or base in (".", ".."):
        raise ValueError(f"Invalid import filename: {filename!r}")
    if Path(base).suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValueError(
            f"Unsupported audio file type: {base!r} (allowed: {', '.join(AUDIO_EXTENSIONS)})"
        )
    target = dataset_dir / base
    target.write_bytes(data)
    return target


# ---------------------------------------------------------------------------
# 模块级单例（与 song_pipeline.get_song_pipeline 的单例模式一致）
# ---------------------------------------------------------------------------

_builder_instance: Optional[DatasetBuilderService] = None


def get_dataset_builder() -> DatasetBuilderService:
    """获取 DatasetBuilderService 稳定单例，供 API 路由复用"""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = DatasetBuilderService(get_settings())
    return _builder_instance
