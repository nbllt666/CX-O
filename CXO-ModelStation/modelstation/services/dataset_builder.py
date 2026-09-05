"""
统一数据集批量构建与 SVC 数据集管理服务（三引擎 + manifest v2）

- 批量生成：输入文本清单（每条约 {text, control?}），按 engine 路由三引擎：
  * voxcpm：子进程调用 engines/VoxCPM-main（现状链路，行为零变化）；
  * cosyvoice3_zero：零样本克隆，经 RuntimeTTSClient 调 cosyvoice 运行时
    （参考音频 base64 data URL 内联，协议真源=CX-O-SERVER/server/qwen3_tts_provider.py）；
  * qwen3_voicedesign：声音设计（音色描述文本），经 RuntimeTTSClient 调 voicedesign 运行时。
  产物统一落盘 So-VITS-SVC 训练期望的目录结构：
      CXO-ModelStation/data/training/sovits_svc/raw/<speaker_name>/*.wav
  （与 sovits_svc_trainer.preprocess() 的 raw_dir 约定一致，
    即 training_data_dir=ModelStation data/training/sovits_svc 时可直接 preprocess）
- MD5 manifest：每个生成文件计算内容 MD5 写入 manifest.json；
  条目指纹（text+mode+control+参数 的 MD5）用于防重复——
  重复提交相同文本+参数时跳过已存在条目，不重复生成。
- manifest v2：条目含 text（合成文本）与 engine 字段；读侧兼容 v1
  （migrate_manifest_to_v2 幂等迁移：缺 text 补 None、缺 engine 补 voxcpm）。
  v2 同时服务双消费：So-VITS-SVC（仅需音频）与 MeloTTS（需音频+文本对）。
- 训练数据目录访问统一经 security_utils.validate_training_data_dir() 集中校验，
  本模块不自定义任何训练根目录常量（_DATASETS_REL_DIR 仅为传入校验器的相对子路径，
  锚点为 security_utils._MS_ROOT = CXO-ModelStation）。
- 参考音频白名单（cosyvoice3_zero）：与 infer 输入白名单同口径
  （sovits_svc.training_data_dir ∪ sovits_svc.input_dir），防任意本地文件路径。
- 异步任务模式：submit 立即返回 task_id，后台 asyncio.create_task 执行，
  get_task 查询进度（done/total/current_text/failed）。

部署要求：单 worker 运行（uvicorn --workers 1），
任务注册表为进程内存状态，不跨进程共享。
运行时引擎依赖 tts_runtime 配置段（Task 1 并行落地；默认工厂经 getattr 防御），
测试经 runtime_client_factory 注入 mock client。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from modelstation.config import ModelStationSettings, get_settings
from modelstation.services.security_utils import validate_training_data_dir

logger = logging.getLogger(__name__)

# 数据集根目录（相对路径，仅作为 validate_training_data_dir 的入参；
# 训练根目录的唯一权威定义在 services/security_utils.py）
_DATASETS_REL_DIR = "data/training/sovits_svc/raw"

# manifest.json 结构版本（v2：条目含 text 与 engine；v1 读侧幂等迁移）
_MANIFEST_VERSION = 2

# 数据集名（speaker 目录名）严格白名单：字母/数字/下划线/连字符，1~64 字符
_DATASET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# 清洗用：不在白名单内的字符替换为下划线（与 sovits_svc_trainer 的 speaker 清洗语义一致）
_SPEAKER_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_-]")

# 允许导入/统计的音频扩展名
AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg")

# 支持的批量数据集生成引擎（SVC 训练数据来源）
ENGINE_VOXCPM = "voxcpm"
ENGINE_COSYVOICE3_ZERO = "cosyvoice3_zero"
ENGINE_QWEN3_VOICEDESIGN = "qwen3_voicedesign"
# 运行时引擎（经 RuntimeTTSClient 走 vLLM HTTP 合成，区别于 voxcpm 子进程链路）
_RUNTIME_ENGINES = (ENGINE_COSYVOICE3_ZERO, ENGINE_QWEN3_VOICEDESIGN)
_SUPPORTED_ENGINES = (ENGINE_VOXCPM,) + _RUNTIME_ENGINES

# ---------------------------------------------------------------------------
# per-dataset_dir 互斥：同一目录并发批量任务会互覆盖 manifest（编号取
# len(entries)+1，两个任务同时基于同一份 entries 计数会产出同名文件 / 丢条目）。
# 键为解析后绝对路径（归一相对/绝对写法差异）；guard 仅保护 dict 的创建读取。
# 用 asyncio.Lock 而非 threading.Lock：批量任务全部运行在宿主事件循环线程上
# （submit_batch → asyncio.create_task，单进程单 loop 部署），
# threading.Lock 跨 await 全程持锁会阻塞 loop 线程导致死锁。
# ---------------------------------------------------------------------------
_DIR_LOCKS_GUARD = threading.Lock()
_DIR_LOCKS: "dict[str, asyncio.Lock]" = {}


def _get_dir_lock(resolved_dir: str) -> asyncio.Lock:
    """按解析后的 dataset_dir 取互斥锁，不存在时在 guard 内创建"""
    with _DIR_LOCKS_GUARD:
        lock = _DIR_LOCKS.get(resolved_dir)
        if lock is None:
            lock = asyncio.Lock()
            _DIR_LOCKS[resolved_dir] = lock
        return lock


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

    调用方在 params 中构造去重维度：
    - voxcpm：沿用旧版字段集（text/mode/control/参考音频/参数），不含 engine，
      保持与既有 manifest 的 voxcpm 条目完全兼容（旧 fingerprint 命中跳过）。
    """
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


def migrate_manifest_to_v2(manifest: dict) -> dict:
    """manifest v1→v2 读侧迁移（幂等，独立可测）。

    - version >= 2：原样返回（不重复迁移，幂等保证）；
    - version < 2（含缺失/非法 version 按 v1 处理）：逐条目补齐 v2 字段——
      缺 ``text`` 补 ``None``（该条目不参与 MeloTTS filelist，由统计报告计数），
      缺 ``engine`` 补 ``"voxcpm"``（v1 时代唯一引擎，语义等价）；
    - 结构异常（entries 非列表）时按空清单骨架修复。

    迁移仅在内存中生效（读侧兼容），落盘由下一次生成任务的 _write_manifest 完成。

    Args:
        manifest: 加载出的 manifest dict（可能为 v1 结构或损坏结构）

    Returns:
        v2 结构的 manifest dict（原对象原位修改后返回）
    """
    if not isinstance(manifest, dict):
        return {"version": _MANIFEST_VERSION, "entries": []}
    try:
        version = int(manifest.get("version") or 1)
    except (TypeError, ValueError):
        version = 1
    if version >= _MANIFEST_VERSION:
        return manifest
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        entries = []
    filled_text = 0
    filled_engine = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if "text" not in entry:
            entry["text"] = None
            filled_text += 1
        if "engine" not in entry:
            entry["engine"] = ENGINE_VOXCPM
            filled_engine += 1
    manifest["version"] = _MANIFEST_VERSION
    manifest["entries"] = entries
    logger.info(
        "manifest v%d→v%d 读侧迁移完成: 补 text=None %d 条, 补 engine %d 条",
        version, _MANIFEST_VERSION, filled_text, filled_engine,
    )
    return manifest


def validate_ref_audio_path(ref_audio_path: str, settings: Optional[ModelStationSettings] = None) -> Path:
    """校验 cosyvoice3_zero 参考音频路径（白名单 fail-closed）。

    口径与 infer 输入白名单一致（spec 冻结：training_data_dir ∪ input_dir，
    见 sovits_svc_infer._validate_audio_path 与 api/sovits_svc.py 的
    allowed_audio_roots），防止任意本地文件路径被读取并 base64 内联进运行时请求。

    Args:
        ref_audio_path: 用户提供的参考音频路径（相对或绝对）
        settings: 配置单例（测试注入用）；缺省 get_settings()

    Returns:
        解析后的安全绝对路径

    Raises:
        ValueError: 路径为空、解析失败或不在任一白名单根之下时
    """
    if settings is None:
        settings = get_settings()
    if not ref_audio_path or not str(ref_audio_path).strip():
        raise ValueError("ref_audio_path must not be empty")
    allowed_roots = [
        Path(settings.sovits_svc.training_data_dir).resolve(),
        Path(settings.sovits_svc.input_dir).resolve(),
    ]
    candidate = Path(ref_audio_path)
    try:
        resolved = candidate.resolve()
    except Exception as e:
        raise ValueError(f"Invalid ref_audio_path: {ref_audio_path}: {e}")
    for root in allowed_roots:
        if resolved.is_relative_to(root):
            return resolved
    raise ValueError(
        f"ref_audio_path must be located under one of {allowed_roots}, got: {resolved}"
    )


@dataclass
class BatchDatasetTask:
    """批量数据集任务记录：内存注册表载体，to_dict() 即 API 响应内容"""

    task_id: str
    speaker_name: str
    dataset_dir: str
    total: int
    mode: str
    created_at: str
    engine: str = "voxcpm"  # 引擎来源（voxcpm）
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

    引擎分发：voxcpm 调用 VoxCPMClient（现状子进程链路，行为零变化）；
    cosyvoice3_zero / qwen3_voicedesign 调用 RuntimeTTSClient（HTTP 运行时合成）。

    client_factory 可注入自定义 voxcpm 客户端工厂（测试用）；
    默认工厂惰性复用 voxcpm 引擎的单例（get_voxcpm_client）。
    runtime_client_factory 接收引擎名，返回该引擎的 RuntimeTTSClient；
    默认工厂按冻结字段名读 settings.tts_runtime（段缺失时经 getattr 防御明确报错），
    测试注入 fake client 以隔离 HTTP。
    """

    def __init__(
        self,
        settings: Optional[ModelStationSettings] = None,
        client_factory: Optional[Callable[[], Any]] = None,
        runtime_client_factory: Optional[Callable[[str], Any]] = None,
    ):
        self._settings = settings if settings is not None else get_settings()
        self._client_factory = client_factory or _default_client_factory
        self._runtime_client_factory = runtime_client_factory or _default_runtime_client_factory
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
        engine_params: Optional[dict] = None,
    ) -> str:
        """
        提交批量数据集生成任务，立即返回 task_id，后台逐条生成。

        Args:
            speaker_name: 目标 speaker（数据集）名，按宽容策略清洗
            texts: 文本清单，每条 {"text": str, "control": Optional[str]}，
                   条目级 control 覆盖任务级 control
            engine: 生成引擎（voxcpm / cosyvoice3_zero / qwen3_voicedesign）
            mode: VoxCPM 模式（design / controllable_clone / ultimate_clone，
                  仅 voxcpm 引擎使用；运行时引擎置空串）
            control: 任务级控制描述（voxcpm 声音设计/克隆控制文本）
            reference_audio_path: controllable_clone 模式参考音频（服务端受控路径）
            prompt_audio_path / prompt_text: ultimate_clone 模式提示音频与文本
            cfg_value / inference_timesteps: 可选推理参数覆盖（voxcpm）
            engine_params: 运行时引擎专属参数——
                cosyvoice3_zero: {"ref_audio_path": str(必填, 白名单路径),
                                  "ref_text": str(可选)};
                qwen3_voicedesign: {"voice_description": str(必填, 音色描述)}

        Returns:
            task_id（uuid4 hex）

        Raises:
            ValueError: texts 为空、引擎不支持、模式/引擎专属参数缺失、
                        参考音频路径白名单校验失败或数据集目录校验失败
        """
        if not texts:
            raise ValueError("texts must not be empty")
        for i, item in enumerate(texts):
            text = item.get("text") if isinstance(item, dict) else None
            if not text or not str(text).strip():
                raise ValueError(f"texts[{i}].text must not be empty")

        # engine 校验：三引擎白名单
        if engine not in _SUPPORTED_ENGINES:
            raise ValueError(
                f"Unsupported engine: {engine!r} (allowed: {', '.join(_SUPPORTED_ENGINES)})"
            )

        # 引擎专属参数校验与归一化（归一化结果同时作为去重指纹的一部分）
        params = dict(engine_params or {})
        if engine == ENGINE_VOXCPM:
            # mode 专属校验（现状行为零变化）
            if mode == "controllable_clone" and not reference_audio_path:
                raise ValueError("reference_audio_path is required for controllable_clone mode")
            if mode == "ultimate_clone":
                if not prompt_audio_path:
                    raise ValueError("prompt_audio_path is required for ultimate_clone mode")
                if not prompt_text:
                    raise ValueError("prompt_text is required for ultimate_clone mode")
        elif engine == ENGINE_COSYVOICE3_ZERO:
            ref_path = params.get("ref_audio_path")
            if not ref_path or not str(ref_path).strip():
                raise ValueError("engine_params.ref_audio_path is required for cosyvoice3_zero engine")
            # 白名单校验（training_data_dir ∪ input_dir），归一化为绝对路径供读盘
            params["ref_audio_path"] = str(validate_ref_audio_path(str(ref_path), self._settings))
            params["ref_text"] = str(params.get("ref_text") or "")
        elif engine == ENGINE_QWEN3_VOICEDESIGN:
            desc = params.get("voice_description")
            if not desc or not str(desc).strip():
                raise ValueError("engine_params.voice_description is required for qwen3_voicedesign engine")
            params["voice_description"] = str(desc).strip()

        # 运行时引擎不使用 voxcpm mode 概念，置空串避免 manifest 语义混淆
        if engine != ENGINE_VOXCPM:
            mode = ""

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
                engine_params=params,
            )
        )
        self._bg_tasks[task_id] = bg
        bg.add_done_callback(lambda t, tid=task_id: self._on_bg_done(tid, t))
        logger.info(
            "批量数据集任务已提交: task_id=%s speaker=%s total=%d engine=%s mode=%r",
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
        engine_params: Optional[dict] = None,
    ) -> None:
        dataset_dir = Path(record.dataset_dir)
        # 同一 dataset_dir 并发批量任务 per-dir 互斥：manifest 读取、条目编号与
        # _write_manifest 落盘全程持锁，防并发任务互覆盖（详见 _DIR_LOCKS 注释）
        dir_lock = _get_dir_lock(os.path.abspath(str(dataset_dir)))
        try:
            record.status = "running"
            async with dir_lock:
                await self._run_locked(
                    record, texts,
                    control=control,
                    reference_audio_path=reference_audio_path,
                    prompt_audio_path=prompt_audio_path,
                    prompt_text=prompt_text,
                    cfg_value=cfg_value,
                    inference_timesteps=inference_timesteps,
                    engine_params=engine_params,
                    dataset_dir=dataset_dir,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            record.current_text = None
            record.finished_at = _now_iso()
            logger.error("批量数据集任务失败: task_id=%s error=%s", record.task_id, exc)

    async def _run_locked(
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
        engine_params: Optional[dict],
        dataset_dir: Path,
    ) -> None:
        """批量生成主体（调用方持有 dataset_dir 互斥锁，同目录任务全程串行）"""
        manifest = self._load_manifest(dataset_dir)
        entries: list[dict] = manifest.setdefault("entries", [])
        by_fingerprint = {e.get("fingerprint"): e for e in entries}

        # 按引擎获取合成 client：voxcpm 走子进程链路，运行时引擎走 HTTP 客户端
        params = dict(engine_params or {})
        if record.engine == ENGINE_VOXCPM:
            client = self._client_factory()
            runtime_client = None
        else:
            client = None
            runtime_client = self._runtime_client_factory(record.engine)

        # voxcpm 推理参数覆盖
        kwargs: dict[str, Any] = {}
        if cfg_value is not None:
            kwargs["cfg_value"] = cfg_value
        if inference_timesteps is not None:
            kwargs["inference_timesteps"] = inference_timesteps

        for index, item in enumerate(texts):
            text = str(item["text"])
            item_control = item.get("control")
            effective_control = control if item_control is None else str(item_control)
            record.current_text = text

            # 去重指纹参数：voxcpm 沿用旧字段集（不含 engine）保持与既有 manifest
            # 兼容（旧 fingerprint 命中跳过）；运行时引擎以 engine+text+engine_params
            # 为去重维度（参数不同即重新生成）
            if record.engine == ENGINE_VOXCPM:
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
            else:
                fp_params = {"engine": record.engine, "text": text, "params": params}
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
                if record.engine == ENGINE_VOXCPM:
                    await self._generate_one(
                        record.engine, client, record.mode, text, effective_control,
                        reference_audio_path, prompt_audio_path, prompt_text,
                        output_path, kwargs,
                    )
                else:
                    await self._generate_one_runtime(
                        record.engine, runtime_client, text, params, output_path,
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
                "engine": record.engine,
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
        """voxcpm 引擎生成单条音频并落盘到 output_path；失败抛异常由上层按条捕获。

        按 mode（design/controllable_clone/ultimate_clone）调用 VoxCPMClient，
        由 client 直接写 output_path（现状行为零变化）。
        """
        if engine != ENGINE_VOXCPM:
            raise ValueError(f"Unsupported engine: {engine!r}")
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

    async def _generate_one_runtime(
        self,
        engine: str,
        runtime_client: Any,
        text: str,
        engine_params: dict,
        output_path: Path,
    ) -> None:
        """运行时引擎（cosyvoice3_zero / qwen3_voicedesign）生成单条音频并落盘。

        协议细节由 RuntimeTTSClient 承载（协议真源=CX-O-SERVER/server/qwen3_tts_provider.py）；
        运行时不可达等失败以 RuntimeTTSError 抛出（含 base_url 与指引），由上层按条捕获。
        """
        params = engine_params or {}
        if engine == ENGINE_QWEN3_VOICEDESIGN:
            await runtime_client.synthesize_voicedesign(
                text=text,
                voice_description=str(params.get("voice_description") or ""),
                output_path=output_path,
            )
            return
        if engine == ENGINE_COSYVOICE3_ZERO:
            await runtime_client.synthesize_cosyvoice_zero(
                text=text,
                ref_audio_path=params.get("ref_audio_path"),
                ref_text=str(params.get("ref_text") or ""),
                output_path=output_path,
            )
            return
        raise ValueError(f"Unsupported runtime engine: {engine!r}")

    # ------------------------------------------------------------------
    # manifest 读写
    # ------------------------------------------------------------------

    def _load_manifest(self, dataset_dir: Path) -> dict:
        """读取 manifest.json；不存在时新建骨架，损坏时告警并按空清单处理。

        v1 结构经 migrate_manifest_to_v2 幂等迁移为 v2（读侧兼容，不落盘——
        下一次生成任务的 _write_manifest 自然持久化为 v2）。
        """
        path = dataset_dir / "manifest.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("entries"), list):
                    return migrate_manifest_to_v2(data)
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
    from modelstation.services.voxcpm_client import get_voxcpm_client

    return get_voxcpm_client(config=get_settings().voxcpm)


def _default_runtime_client_factory(engine: str):
    """默认运行时 TTS 客户端工厂：按引擎读 settings.tts_runtime 冻结字段构造 RuntimeTTSClient。

    tts_runtime 配置段由并行分支（Task 1.3）落地；并行时序下段缺失时经
    getattr 防御抛 RuntimeError（含「配置段未就绪」提示），不崩溃服务。
    字段名冻结：voicedesign_base_url / voicedesign_model / cosyvoice_base_url /
    cosyvoice_model / timeout_seconds / sample_rate。
    """
    from modelstation.services.runtime_tts_client import RuntimeTTSClient

    settings = get_settings()
    tts_runtime = getattr(settings, "tts_runtime", None)
    if tts_runtime is None:
        raise RuntimeError(
            "tts_runtime 配置段未就绪（依赖并行分支 config 落地），无法构造运行时 TTS 客户端"
        )
    if engine == ENGINE_QWEN3_VOICEDESIGN:
        base_url = tts_runtime.voicedesign_base_url
        model = tts_runtime.voicedesign_model
    elif engine == ENGINE_COSYVOICE3_ZERO:
        base_url = tts_runtime.cosyvoice_base_url
        model = tts_runtime.cosyvoice_model
    else:
        raise ValueError(f"Unsupported runtime engine: {engine!r}")
    return RuntimeTTSClient(
        base_url=base_url,
        model=model,
        timeout_seconds=tts_runtime.timeout_seconds,
        sample_rate=tts_runtime.sample_rate,
    )


# ---------------------------------------------------------------------------
# 数据集管理（列表 / 导入落盘 / 删除），供 API 层调用
# ---------------------------------------------------------------------------


def get_manifest_stats(dataset_dir: Path) -> dict:
    """读取数据集 manifest 统计：版本、条目数与 text 完整率（独立可测）。

    统计基于磁盘上的原始 manifest（不做 v1→v2 迁移，如实报告版本）。

    Returns:
        {"manifest_version": int|None, "entry_count": int,
         "text_count": int, "text_ratio": float|None}
        （manifest 缺失/损坏时 version=None、ratio=None；entries 为空时 ratio=None）
    """
    stats = {
        "manifest_version": None,
        "entry_count": 0,
        "text_count": 0,
        "text_ratio": None,
    }
    path = dataset_dir / "manifest.json"
    if not path.is_file():
        return stats
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("统计 manifest 读取失败: %s (%s)", path, exc)
        return stats
    if not isinstance(data, dict):
        return stats
    stats["manifest_version"] = data.get("version")
    entries = data.get("entries")
    if not isinstance(entries, list):
        return stats
    stats["entry_count"] = len(entries)
    text_count = sum(
        1 for e in entries if isinstance(e, dict) and e.get("text")
    )
    stats["text_count"] = text_count
    if entries:
        stats["text_ratio"] = round(text_count / len(entries), 4)
    return stats


def list_datasets() -> list[dict]:
    """列出全部数据集：扫描数据集根目录下的 speaker 子目录。

    Returns:
        [{name, file_count, total_size_bytes, created_at, has_manifest,
          manifest_version, entry_count, text_count, text_ratio}]，按名称升序。
        manifest 版本与 text 完整率（含 text 条目占比）供统一数据集双消费
        （So-VITS-SVC 仅音频 / MeloTTS 需音频+文本对）选型。
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
        entry = {
            "name": child.name,
            "file_count": len(audio_files),
            "total_size_bytes": total_size,
            "created_at": datetime.fromtimestamp(child.stat().st_ctime)
            .astimezone()
            .isoformat(timespec="seconds"),
            "has_manifest": (child / "manifest.json").is_file(),
        }
        entry.update(get_manifest_stats(child))
        datasets.append(entry)
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
# 模块级单例（与原 VWS 的单例模式一致）
# ---------------------------------------------------------------------------

_builder_instance: Optional[DatasetBuilderService] = None


def get_dataset_builder() -> DatasetBuilderService:
    """获取 DatasetBuilderService 稳定单例，供 API 路由复用"""
    global _builder_instance
    if _builder_instance is None:
        _builder_instance = DatasetBuilderService(get_settings())
    return _builder_instance
