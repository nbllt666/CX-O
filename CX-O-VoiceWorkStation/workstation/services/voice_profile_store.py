"""
目标模型音域画像存储（change-id: enhance-cover-pitch-analysis-duet Task 2）

职责：扫描 ModelStation 训练数据 raw/<speaker>/*.wav（VWS 只读，跨服务同
sovits_svc.models_dir 模式），逐 speaker 计算人声音域画像并 MD5 缓存落盘
data/voice_profiles/<speaker>.json（数据集内容指纹变化自动重算）。

冻结契约（Task 3 并行分支 duet_pipeline 将从本模块 import，签名与 None 语义不可变）：
- get_profile(speaker_name: str) -> Optional[dict]
    无训练数据 / 数据集为空 / 全部文件不可算 / 非法名 → None（不抛错）
- list_profiles() -> list[dict]
    每项含 speaker_name + 画像字段 + dataset_md5 + computed_at；只含有画像的 speaker

speaker 名清洗对齐 CXO-ModelStation sovits_svc_trainer 的 so-vits 惯例
（[^A-Za-z0-9_-] → "_"，strip 后空回退）；查表场景非法名（清洗后为空）返回 None。

聚合口径：逐文件 analyze_pitch 得到各文件 VoiceProfile（仅含 median/P10/P90 三个
MIDI 汇总值），三值合并为 MIDI 池后取 median/P10/P90 作为 speaker 画像（汇总统计
池化近似，规格见 tasks.md SubTask 2.1）。数据集指纹 = 文件名+大小+mtime_ns 的
md5（避免逐文件读内容的开销）。

性能护栏：单 speaker wav 数超过抽样上限（_MAX_ANALYZE_FILES，默认 30）时均匀
抽样，避免 analyze 端点首次调用卡死。config.py 已冻结（Task 1 交付），上限以
模块常量承载，测试可 monkeypatch；后续如需运维可调再走配置契约变更流程。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from workstation.config import get_settings
from workstation.services.vocal_analysis import (
    VoiceAnalysisError,
    VoiceProfile,
    analyze_pitch,
)

logger = logging.getLogger(__name__)

# speaker 名白名单外字符（对齐 CXO-ModelStation sovits_svc_trainer._SPEAKER_NAME_PATTERN）
_SPEAKER_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_-]")
# 单 speaker 最多参与画像计算的 wav 数（均匀抽样）
_MAX_ANALYZE_FILES = 30

# 画像 dict 的完整键集（冻结契约的一部分：get_profile/list_profiles 返回结构）
PROFILE_KEYS = {
    "speaker_name",
    "f0_median_hz",
    "f0_median_midi",
    "range_low_midi",
    "range_high_midi",
    "range_span_semitones",
    "sample_count",
    "dataset_md5",
    "computed_at",
}


def sanitize_speaker_name(name: str) -> Optional[str]:
    """清洗 speaker 名（对齐 so-vits 惯例）；非法名（空/清洗后为空）返回 None。

    白名单 [A-Za-z0-9_-] 外字符（含路径分隔符与点号）替换为 "_"，
    首尾下划线剔除——天然防路径穿越（清洗结果不可能含 / \\ ..）。
    """
    if not name or not isinstance(name, str):
        return None
    cleaned = _SPEAKER_NAME_PATTERN.sub("_", name).strip("_")
    return cleaned or None


def _raw_root() -> Path:
    """训练数据 raw 根目录（cover_analysis.training_data_dir/raw，只读）。"""
    return Path(get_settings().cover_analysis.training_data_dir) / "raw"


def _speaker_dir(speaker_name: str) -> Optional[Path]:
    """speaker 训练数据目录（resolve 后必须仍位于 raw 根内，防御性兜底）。"""
    cleaned = sanitize_speaker_name(speaker_name)
    if cleaned is None:
        return None
    root = _raw_root().resolve()
    d = (root / cleaned).resolve()
    if not d.is_relative_to(root):
        return None
    return d


def _list_wavs(speaker_dir: Path) -> list[Path]:
    """列出 speaker 目录下全部 wav（按文件名排序，保证抽样与指纹确定性）。"""
    if not speaker_dir.exists():
        return []
    return sorted(p for p in speaker_dir.glob("*.wav") if p.is_file())


def _dataset_md5(wav_files: list[Path]) -> str:
    """数据集内容指纹：文件名+大小+mtime_ns 的 md5（不逐文件读内容）。"""
    digest = hashlib.md5()
    for p in sorted(wav_files, key=lambda x: x.name):
        st = p.stat()
        digest.update(f"{p.name}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8"))
    return digest.hexdigest()


def _uniform_sample(files: list[Path], max_files: int) -> list[Path]:
    """超过上限时均匀抽样（保序、保端点；不超过时原样返回）。"""
    total = len(files)
    if max_files <= 0 or total <= max_files:
        return list(files)
    step = total / max_files
    seen: set[int] = set()
    selected: list[Path] = []
    for i in range(max_files):
        idx = min(total - 1, int(i * step))
        if idx not in seen:
            seen.add(idx)
            selected.append(files[idx])
    return selected


def _cache_path(speaker: str) -> Path:
    return Path(get_settings().cover_analysis.voice_profiles_dir) / f"{speaker}.json"


def _load_cache(speaker: str, dataset_md5: str) -> Optional[dict]:
    """读取画像缓存；文件缺失/损坏/MD5 不一致 → None（走重算）。"""
    cache_file = _cache_path(speaker)
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        logger.warning("Voice profile cache unreadable (%s): %s", cache_file, e)
        return None
    if not isinstance(data, dict) or data.get("dataset_md5") != dataset_md5:
        return None
    if not PROFILE_KEYS.issubset(data.keys()):
        return None
    return data


def _save_cache(speaker: str, payload: dict) -> None:
    """画像缓存落盘（临时文件 + os.replace 原子替换；失败仅告警不抛错）。"""
    cache_file = _cache_path(speaker)
    tmp_file = cache_file.with_suffix(".json.tmp")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_file, cache_file)
    except OSError as e:
        logger.warning("Voice profile cache write failed (%s): %s", cache_file, e)


def _aggregate(
    speaker: str, profiles: list[VoiceProfile], dataset_md5: str
) -> dict:
    """聚合各文件画像为 speaker 级画像 dict（MIDI 三值池化 → median/P10/P90）。"""
    midi_pool: list[float] = []
    for p in profiles:
        midi_pool.extend(
            [p.range_low_midi, p.f0_median_midi, p.range_high_midi]
        )
    pool = np.asarray(midi_pool, dtype=float)
    f0_median_hz = float(np.median([p.f0_median_hz for p in profiles]))
    range_low = float(np.percentile(pool, 10))
    range_high = float(np.percentile(pool, 90))
    return {
        "speaker_name": speaker,
        "f0_median_hz": f0_median_hz,
        "f0_median_midi": float(np.median(pool)),
        "range_low_midi": range_low,
        "range_high_midi": range_high,
        "range_span_semitones": range_high - range_low,
        "sample_count": len(profiles),
        "dataset_md5": dataset_md5,
        "computed_at": datetime.now().isoformat(timespec="microseconds"),
    }


def get_profile(speaker_name: str) -> Optional[dict]:
    """获取目标模型音域画像（冻结契约：Task 3 duet_pipeline 消费）。

    流程：清洗名 → 扫描 raw/<speaker>/*.wav → 数据集 MD5 → 缓存命中直接返回；
    未命中则逐文件 analyze_pitch（f0_confidence 取 config）→ 聚合 → 落盘缓存。

    Returns:
        画像 dict（PROFILE_KEYS 全键）；无训练数据 / 目录不存在 / 数据集为空 /
        全部文件不可算 / 非法名 → None（不抛错，缓存不动）。
    """
    f0_confidence = get_settings().cover_analysis.f0_confidence
    speaker_dir = _speaker_dir(speaker_name)
    if speaker_dir is None:
        logger.info("Voice profile: invalid speaker name %r", speaker_name)
        return None

    wavs = _list_wavs(speaker_dir)
    if not wavs:
        logger.info("Voice profile: no training wavs for speaker %r", speaker_name)
        return None

    dataset_md5 = _dataset_md5(wavs)
    speaker = sanitize_speaker_name(speaker_name) or ""
    cached = _load_cache(speaker, dataset_md5)
    if cached is not None:
        logger.info(
            "Voice profile cache hit: %s (md5=%s, files=%d)",
            speaker, dataset_md5, len(wavs),
        )
        return cached

    selected = _uniform_sample(wavs, _MAX_ANALYZE_FILES)
    profiles: list[VoiceProfile] = []
    for wav in selected:
        try:
            profiles.append(analyze_pitch(wav, f0_confidence))
        except VoiceAnalysisError as e:
            logger.warning("Skip unanalyzable training wav %s: %s", wav.name, e)
        except Exception as e:  # noqa: BLE001 - 单文件意外错误不毁掉整份画像
            logger.warning("Skip training wav %s on unexpected error: %s", wav.name, e)

    if not profiles:
        logger.warning(
            "Voice profile: all %d training wavs unanalyzable for speaker %r",
            len(selected), speaker,
        )
        return None

    payload = _aggregate(speaker, profiles, dataset_md5)
    _save_cache(speaker, payload)
    logger.info(
        "Voice profile computed: %s (files=%d/%d, median=%.2f MIDI, span=%.2f st)",
        speaker, len(profiles), len(wavs),
        payload["f0_median_midi"], payload["range_span_semitones"],
    )
    return payload


def list_profiles() -> list[dict]:
    """全部 speaker 画像列表（冻结契约）。

    扫描 raw/ 下全部 speaker 目录，只返回有画像的 speaker（数据集为空/不可算的
    不含），按 speaker_name 升序。
    """
    root = _raw_root()
    if not root.exists():
        return []
    profiles: list[dict] = []
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        profile = get_profile(entry.name)
        if profile is not None:
            profiles.append(profile)
    return profiles
