"""数据集编号注册表（统一流程自动编号 → 数据集目录解析）

一套流程的产物约定（qwen3 初始参考音频 → cosyvoice 批量语料 → 数据集编号）：
每次统一流程生成完成后，数据集获得全局唯一编号（DS-001、DS-002 …），
训练入口（MeloTTS 预处理 / So-VITS-SVC 预处理与训练）可直接以编号选择数据集，
无需再手写目录路径。

存储：注册表 JSON 落盘在训练数据根（training_data_root()/dataset_registry.json），
结构 {"version": 1, "next_seq": N, "datasets": {id: entry}}；
- id     ："DS-001" 形式（零填充 3 位，超 999 自然进位为 4 位）；
- name   ：数据集目录名（缺省与 id 相同，同受目录名白名单约束）；
- entry  ：含 created_at / engine / ref_audio / ref_text / task_id 等来源元数据。

解析宽容度：resolve 接受 "DS-001" / "ds-1" / "1" 等写法，统一归一化为规范 id。
单 worker 部署（uvicorn --workers 1）+ 同步文件读写，注册表操作天然串行；
写侧采用临时文件 + os.replace 原子替换。
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from modelstation.services.security_utils import training_data_root

logger = logging.getLogger(__name__)

_REGISTRY_VERSION = 1
# 目录名白名单（与 dataset_builder._DATASET_NAME_PATTERN 同口径；此处独立定义避免循环导入）
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ID_PREFIX = "DS"


class DatasetRegistryError(ValueError):
    """编号/名称非法或注册表状态不满足预期（统一 400 语义）。"""


def registry_path() -> Path:
    """注册表落盘路径（训练数据根下，安装态跟随注入数据根）。"""
    return Path(training_data_root()) / "dataset_registry.json"


def _load() -> dict:
    path = registry_path()
    if not path.is_file():
        return {"version": _REGISTRY_VERSION, "next_seq": 1, "datasets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("数据集注册表读取失败，按空注册表处理: %s (%s)", path, exc)
        return {"version": _REGISTRY_VERSION, "next_seq": 1, "datasets": {}}
    if not isinstance(data, dict) or not isinstance(data.get("datasets"), dict):
        return {"version": _REGISTRY_VERSION, "next_seq": 1, "datasets": {}}
    data.setdefault("next_seq", 1)
    return data


def _save(data: dict) -> None:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def normalize_dataset_id(raw: str) -> str:
    """归一化编号写法："ds-1" / "1" / "DS-001" → "DS-001"。

    Raises:
        DatasetRegistryError: 写法无法解析为编号时
    """
    text = str(raw or "").strip().upper()
    if not text:
        raise DatasetRegistryError("数据集编号不能为空")
    if text.isdigit():
        seq = int(text)
    elif text.startswith(_ID_PREFIX + "-") and text[len(_ID_PREFIX) + 1 :].isdigit():
        seq = int(text[len(_ID_PREFIX) + 1 :])
    else:
        raise DatasetRegistryError(
            f"数据集编号写法无法解析: {raw!r}（示例：DS-001 / 1）"
        )
    if seq < 1:
        raise DatasetRegistryError(f"数据集编号须为正整数: {raw!r}")
    return f"{_ID_PREFIX}-{seq:03d}" if seq < 1000 else f"{_ID_PREFIX}-{seq:04d}"


def register_dataset(
    name: Optional[str] = None, *, engine: str = "pipeline", **meta
) -> dict:
    """登记一个新数据集，分配下一个编号，返回 {"dataset_id", "name"}。

    Args:
        name: 数据集目录名；缺省/空时与编号相同。非法名称抛 DatasetRegistryError。
        engine: 生成来源引擎（统一流程固定 "pipeline"）。
        **meta: 附加来源元数据（ref_audio / ref_text / task_id 等，值须可 JSON 序列化）。
    """
    if name is not None:
        name = str(name).strip()
        if not name or not _NAME_PATTERN.match(name):
            raise DatasetRegistryError(
                f"Invalid dataset name: {name!r}. "
                "Only letters, digits, underscore and hyphen are allowed (1-64 chars)."
            )
    data = _load()
    seq = int(data.get("next_seq") or 1)
    dataset_id = f"{_ID_PREFIX}-{seq:03d}" if seq < 1000 else f"{_ID_PREFIX}-{seq:04d}"
    while dataset_id in data["datasets"]:  # 防御：手工改动注册表导致的占用
        seq += 1
        dataset_id = f"{_ID_PREFIX}-{seq:03d}" if seq < 1000 else f"{_ID_PREFIX}-{seq:04d}"
    entry = {
        "name": name or dataset_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "engine": engine,
    }
    entry.update({k: v for k, v in meta.items() if v is not None})
    data["datasets"][dataset_id] = entry
    data["next_seq"] = seq + 1
    _save(data)
    logger.info("数据集已登记: %s -> %s", dataset_id, entry["name"])
    return {"dataset_id": dataset_id, "name": entry["name"]}


def get_entry(dataset_id: str) -> dict:
    """按编号取登记项；未登记时抛 DatasetRegistryError。"""
    canonical = normalize_dataset_id(dataset_id)
    data = _load()
    entry = data["datasets"].get(canonical)
    if entry is None:
        raise DatasetRegistryError(f"数据集编号不存在: {canonical}")
    return {"dataset_id": canonical, **entry}


def update_entry(dataset_id: str, **meta) -> None:
    """就地补充登记项元数据（如 task_id / ref_audio）；编号不存在时静默忽略。"""
    try:
        canonical = normalize_dataset_id(dataset_id)
    except DatasetRegistryError:
        return
    data = _load()
    entry = data["datasets"].get(canonical)
    if entry is None:
        return
    entry.update({k: v for k, v in meta.items() if v is not None})
    _save(data)


def all_entries() -> dict:
    """全量登记项（只读快照，{dataset_id: entry}）。"""
    return dict(_load()["datasets"])


def attach_dataset_ids(datasets: list[dict]) -> list[dict]:
    """把编号并入 list_datasets 输出（按目录名匹配；未登记的编号置 None）。"""
    by_name = {entry["name"]: ds_id for ds_id, entry in all_entries().items()}
    for item in datasets:
        item["dataset_id"] = by_name.get(item.get("name"))
    return datasets


def new_task_id() -> str:
    """任务跟踪用 uuid（注册表不关心，供调用方统一生成）。"""
    return uuid.uuid4().hex
