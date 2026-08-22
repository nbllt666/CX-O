"""anchors：锚点（蒸馏角色卡）样本加载与 DPO 数据混合。

锚点样本来源为蒸馏角色卡数据路径（config.character_cards_dir，默认
CXO-Tuner/data/anchors），支持 .json / .jsonl / .md 三种格式：

  - json：可为数组（每项含 prompt/response 或 instruction/output）或单对象；
  - jsonl：每行一个样本对象；
  - md：按文件视为一条角色卡描述样本（prompt 取文件名占位）。

sample_anchor_subset 按 config.anchor_ratio 与 DPO 样本量计算应采样的锚点
数量（target = num_dpo * ratio / (1 - ratio)），返回用于 SFT 的锚点子集。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("cxo_tuner.trainer.anchors")

_ANCHOR_EXTS = (".json", ".jsonl", ".md")
_PROMPT_KEYS = ("prompt", "instruction", "input")
_RESPONSE_KEYS = ("response", "output", "completion")


def _normalize(sample: Dict[str, Any]) -> Dict[str, str]:
    """把任意键名的样本规整为 {prompt, response}。"""
    prompt = ""
    for key in _PROMPT_KEYS:
        if key in sample and sample[key]:
            prompt = str(sample[key])
            break
    response = ""
    for key in _RESPONSE_KEYS:
        if key in sample and sample[key]:
            response = str(sample[key])
            break
    if not prompt and not response:
        return {}
    return {"prompt": prompt, "response": response}


def load_anchor_samples(character_cards_dir: str) -> List[Dict[str, str]]:
    """从目录递归加载锚点样本，返回规整后的 {prompt, response} 列表。"""
    if not os.path.isdir(character_cards_dir):
        logger.warning("锚点目录不存在，锚点为空: %r", character_cards_dir)
        return []
    samples: List[Dict[str, str]] = []
    for root, _dirs, files in os.walk(character_cards_dir):
        for name in sorted(files):
            if not name.lower().endswith(_ANCHOR_EXTS):
                continue
            path = os.path.join(root, name)
            loaded = _load_file(path, name)
            samples.extend(loaded)
    # 去重（prompt+response 相同）
    seen: set = set()
    dedup: List[Dict[str, str]] = []
    for s in samples:
        key = (s.get("prompt", ""), s.get("response", ""))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(s)
    logger.info(
        "锚点加载: dir=%r raw_samples=%d dedup=%d", character_cards_dir, len(samples), len(dedup)
    )
    return dedup


def _load_file(path: str, name: str) -> List[Dict[str, str]]:
    ext = os.path.splitext(name)[1].lower()
    out: List[Dict[str, str]] = []
    try:
        if ext == ".md":
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            if content.strip():
                out.append({"prompt": os.path.splitext(name)[0], "response": content})
        elif ext == ".jsonl":
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sample = _normalize(json.loads(line))
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if sample:
                        out.append(sample)
        elif ext == ".json":
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        sample = _normalize(item)
                        if sample:
                            out.append(sample)
            elif isinstance(data, dict):
                sample = _normalize(data)
                if sample:
                    out.append(sample)
    except (OSError, ValueError):
        return []
    return out


def sample_anchor_subset(
    num_dpo: int, anchor_ratio: float, anchors: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """按 anchor_ratio 从锚点样本中抽取 SFT 子集。

    target = num_dpo * ratio / (1 - ratio)，使锚点在混合样本中占比约为 ratio；
    不足或超量时以可用锚点数量截断。
    """
    if not anchors or num_dpo <= 0:
        return []
    ratio = min(1.0, max(0.0, float(anchor_ratio)))
    if ratio >= 1.0:
        logger.info("锚点采样: anchor_ratio=1.0 返回全部 %d 条", len(anchors))
        return list(anchors)
    target = num_dpo * ratio / (1.0 - ratio)
    count = min(int(target + 0.5), len(anchors))
    logger.info("锚点采样: num_dpo=%d ratio=%.2f target=%.2f count=%d available=%d",
                num_dpo, ratio, target, count, len(anchors))
    return list(anchors[:count])