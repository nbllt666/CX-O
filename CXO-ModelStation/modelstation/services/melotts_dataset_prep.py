"""
MeloTTS 训练数据准备（manifest v2 统一数据集 → MeloTTS 训练 filelist）

change-id: extend-modelstation-standalone-melotts-datasets（spec「MeloTTS 微调训练」：
melotts_dataset_prep 从 manifest v2 抽取 text 条目生成 train/val filelist，
音素化由 MeloTTS 管线承担——本模块只做切分与落盘，不做文本清洗）。

filelist 行格式（以 engines/MeloTTS 实码为准，覆盖 spec 草案三列语义）：
    音频绝对路径|说话人名|语言|文本
依据：
  - engines/MeloTTS/docs/training.md 官方 metadata 格式说明；
  - melo/preprocess_text.py:54 `utt, spk, language, text = line.strip().split("|")`；
  - melo/data/example/metadata.list 实例（`.../000.wav|EN-default|EN|<text>`）。
即官方管线消费四列（第三列为语言代码），本模块按实码产出四列。

切分规则（spec 冻结）：
  - 默认 95/5（val_ratio=0.05）；
  - 总数 ≥ 5 时 val 至少 1 条；总数 < 5 时全进 train 并在 split_note 报告；
  - 切分为确定性等距抽样（可经 manifest_prep.json 复现）。

排除规则（spec 冻结）：
  - manifest v1 经 dataset_builder.migrate_manifest_to_v2 读侧迁移（text=None），
    text=null/缺失条目排除并计数（excluded_no_text）；
  - 条目音频文件在磁盘缺失时排除并计数（excluded_missing_file），不崩溃。

产出（落盘训练工作目录，默认 <melotts training_data_dir>/<speaker>/）：
  - train.txt / val.txt：四列 filelist；
  - metadata.list：train + val 全量合并（官方 preprocess_text.py 输入）；
  - manifest_prep.json：切分元数据（复现用）。

路径全部经 security_utils.validate_training_data_dir / config 绝对值注入，
对 CWD 免疫（rules-0 §三）。
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from modelstation.services.dataset_builder import migrate_manifest_to_v2, sanitize_speaker_name
from modelstation.services.security_utils import validate_training_data_dir

logger = logging.getLogger(__name__)

# filelist 结构版本（prep 产物自身元数据的版本，与 dataset manifest v2 区分）
_PREP_MANIFEST_VERSION = 1

# 默认验证集占比（spec：默认 95/5 切分）
DEFAULT_VAL_RATIO = 0.05
# 进入比例切分的最小条目总数：低于该值全部进 train（spec：总数<5 时全进 train 并报告）
MIN_TOTAL_FOR_VAL_SPLIT = 5


def _now_iso() -> str:
    """本地时区 ISO8601 时间戳（秒级）"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sanitize_line_field(text: str) -> str:
    """清洗文本字段：filelist 以 '|' 作列分隔符，文本内的 '|' 与换行必须替换。

    '|' → 空格；换行/回车 → 空格。避免破坏官方管线的 split("|") 解析。
    """
    cleaned = str(text).replace("|", " ")
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    return cleaned.strip()


def _load_manifest(dataset_dir: Path) -> dict:
    """读取 speaker 数据集 manifest.json 并做 v1→v2 读侧幂等迁移。

    复用 dataset_builder.migrate_manifest_to_v2 的迁移语义（text=None 补齐），
    保证 v1 数据集的 text 缺失条目被统一排除并计数。

    Raises:
        ValueError: manifest.json 不存在或不可解析时
    """
    path = dataset_dir / "manifest.json"
    if not path.is_file():
        raise ValueError(
            f"manifest.json not found in dataset dir: {dataset_dir} "
            "（请先通过批量语料生成或导入建立数据集）"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to read manifest.json: {path}: {exc}")
    return migrate_manifest_to_v2(data)


def _collect_entries(
    dataset_dir: Path, entries: list
) -> tuple[list[tuple[str, str, str]], int, int, int]:
    """遍历 manifest 条目，抽取 (音频绝对路径, speaker, text) 可用条目并计数排除项。

    Returns:
        (usable, total, excluded_no_text, excluded_missing_file)
    """
    usable: list[tuple[str, str, str]] = []
    excluded_no_text = 0
    excluded_missing_file = 0
    for entry in entries:
        if not isinstance(entry, dict):
            excluded_no_text += 1
            continue
        text = entry.get("text")
        if not text or not str(text).strip():
            # v1 迁移条目（text=None）或空文本：不参与 MeloTTS filelist（spec 冻结）
            excluded_no_text += 1
            continue
        file_name = entry.get("file")
        if not file_name:
            excluded_missing_file += 1
            continue
        audio_path = dataset_dir / str(file_name)
        if not audio_path.is_file():
            # manifest 有记录但文件缺失：排除并计数，不崩溃（spec 冻结）
            excluded_missing_file += 1
            continue
        speaker = str(entry.get("speaker") or "").strip()
        usable.append((str(audio_path.resolve()), speaker, _sanitize_line_field(str(text))))
    return usable, len(entries), excluded_no_text, excluded_missing_file


def _split_indices(total: int, val_ratio: float) -> tuple[list[int], list[int], str]:
    """确定性等距切分：返回 (train_indices, val_indices, split_note)。

    - total < MIN_TOTAL_FOR_VAL_SPLIT：全进 train，note 说明；
    - 否则 val_count = max(1, floor(total * val_ratio))，等距抽样保证
      val 条目均匀分布于整个数据集（可复现，不依赖随机数）。
    """
    if total < MIN_TOTAL_FOR_VAL_SPLIT:
        return (
            list(range(total)),
            [],
            f"条目总数 {total} < {MIN_TOTAL_FOR_VAL_SPLIT}，全部进入 train（未做比例切分）",
        )
    val_count = max(1, int(total * val_ratio))
    val_count = min(val_count, total - 1)  # train 至少保留 1 条
    val_indices = sorted({(i * total) // val_count for i in range(val_count)})
    val_set = set(val_indices)
    train_indices = [i for i in range(total) if i not in val_set]
    return train_indices, val_indices, f"按 {1 - val_ratio:.0%}/{val_ratio:.0%} 切分"


def prepare_filelists(
    dataset_dir: str,
    speaker_name: Optional[str] = None,
    output_dir: Optional[str] = None,
    language: str = "ZH",
    val_ratio: float = DEFAULT_VAL_RATIO,
) -> dict:
    """统一数据集（manifest v2）→ MeloTTS 训练 filelist（train/val/metadata + prep 元数据）。

    Args:
        dataset_dir: speaker 数据集目录（含 manifest.json 与音频文件），
                     经 validate_training_data_dir 集中校验（data/training 之下）
        speaker_name: filelist 中的说话人名；缺省取数据集目录名（清洗后）
        output_dir: 产出目录；缺省 <settings.melotts.training_data_dir>/<speaker>
        language: 语言代码（MeloTTS filelist 第三列；默认 ZH，来自 config.melotts.language）
        val_ratio: 验证集占比（默认 0.05）

    Returns:
        统计 dict：{total, used, excluded_no_text, excluded_missing_file,
        train_count, val_count, speaker_name, language, split_note,
        output_dir, train_file, val_file, metadata_file, prep_manifest_file, created_at}

    Raises:
        ValueError: dataset_dir 非法/manifest 缺失或不可解析/无可用条目时
    """
    if not 0 < val_ratio < 1:
        raise ValueError(f"val_ratio must be in (0, 1), got: {val_ratio}")
    lang = ("" if language is None else str(language)).strip()
    if not lang:
        raise ValueError("language must not be empty")

    resolved_dataset_dir = validate_training_data_dir(str(dataset_dir))
    speaker = sanitize_speaker_name(speaker_name or resolved_dataset_dir.name)

    manifest = _load_manifest(resolved_dataset_dir)
    entries = manifest.get("entries") or []
    usable, total, excluded_no_text, excluded_missing_file = _collect_entries(
        resolved_dataset_dir, entries
    )
    if not usable:
        raise ValueError(
            "数据集无可用条目（全部被排除）："
            f"total={total}, excluded_no_text={excluded_no_text}, "
            f"excluded_missing_file={excluded_missing_file}。"
            "MeloTTS 训练需要含 text 的 manifest v2 条目（v1 历史数据集无 text 不参与）。"
        )

    train_idx, val_idx, split_note = _split_indices(len(usable), val_ratio)

    if output_dir:
        out_dir = Path(output_dir)
    else:
        from modelstation.config import get_settings

        out_dir = Path(get_settings().melotts.training_data_dir) / speaker
    out_dir.mkdir(parents=True, exist_ok=True)

    def _line(item: tuple[str, str, str]) -> str:
        audio_path, spk, text = item
        return f"{audio_path}|{spk or speaker}|{lang}|{text}"

    train_lines = [_line(usable[i]) for i in train_idx]
    val_lines = [_line(usable[i]) for i in val_idx]
    metadata_lines = train_lines + val_lines

    train_file = out_dir / "train.txt"
    val_file = out_dir / "val.txt"
    metadata_file = out_dir / "metadata.list"
    prep_manifest_file = out_dir / "manifest_prep.json"

    train_file.write_text("\n".join(train_lines) + "\n", encoding="utf-8")
    val_file.write_text("\n".join(val_lines) + "\n", encoding="utf-8")
    metadata_file.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")

    prep_meta = {
        "version": _PREP_MANIFEST_VERSION,
        "created_at": _now_iso(),
        "dataset_dir": str(resolved_dataset_dir),
        "speaker_name": speaker,
        "language": lang,
        "val_ratio": val_ratio,
        "total": total,
        "used": len(usable),
        "excluded_no_text": excluded_no_text,
        "excluded_missing_file": excluded_missing_file,
        "train_count": len(train_lines),
        "val_count": len(val_lines),
        "split_note": split_note,
        "train_file": str(train_file),
        "val_file": str(val_file),
        "metadata_file": str(metadata_file),
    }
    tmp_path = out_dir / "manifest_prep.json.tmp"
    tmp_path.write_text(
        json.dumps(prep_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp_path, prep_manifest_file)

    logger.info(
        "MeloTTS 数据准备完成: dataset=%s speaker=%s total=%d used=%d "
        "train=%d val=%d excluded_no_text=%d excluded_missing_file=%d out=%s",
        resolved_dataset_dir, speaker, total, len(usable),
        len(train_lines), len(val_lines), excluded_no_text, excluded_missing_file, out_dir,
    )
    stats = dict(prep_meta)
    stats["output_dir"] = str(out_dir)
    stats["prep_manifest_file"] = str(prep_manifest_file)
    return stats


def find_latest_prep(training_data_dir: Optional[str] = None) -> dict:
    """扫描训练数据目录，返回最近一次 prep 的 manifest_prep.json 内容。

    trainer 消费入口：train 请求未携带 speaker 时，取最近一次 preprocess 产出。

    Returns:
        manifest_prep.json 的 dict 内容（含 metadata_file/train_file/val_file 路径）

    Raises:
        FileNotFoundError: 训练数据目录下不存在任何 manifest_prep.json 时
    """
    if training_data_dir:
        root = Path(training_data_dir)
    else:
        from modelstation.config import get_settings

        root = Path(get_settings().melotts.training_data_dir)
    best_path: Optional[Path] = None
    best_mtime = -1.0
    if root.is_dir():
        for candidate in root.glob("*/manifest_prep.json"):
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best_mtime = mtime
                best_path = candidate
    if best_path is None:
        raise FileNotFoundError(
            f"未找到 MeloTTS 数据准备产物（{root}/*/manifest_prep.json）。"
            "请先调用 POST /api/melotts/preprocess 生成训练 filelist。"
        )
    data = json.loads(best_path.read_text(encoding="utf-8"))
    data["prep_manifest_file"] = str(best_path)
    return data
