"""训练后声码器回收：把微调检查点的 dec.* 换回官方底模权重。

背景：官方只发布 G（无判别器 D），微调时随机 D 的对抗梯度会把 44.1k HiFi-GAN
带偏，产出「电音」。保持声学部分照常训练，训练结束后统一换回官方 dec，可同时
保留发音准确度与干净音色。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch


def _state_dict(obj):
    return obj["model"] if isinstance(obj, dict) and "model" in obj else obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--base-ckpt", required=True)
    args = ap.parse_args()

    model_dir = Path(args.model_dir)
    base_path = Path(args.base_ckpt)
    if not model_dir.is_dir():
        print(f"model dir missing: {model_dir}", file=sys.stderr)
        return 2
    base_obj = torch.load(base_path, map_location="cpu")
    base_sd = _state_dict(base_obj)

    swapped = []
    for ckpt in sorted(model_dir.glob("G_*.pth")):
        obj = torch.load(ckpt, map_location="cpu")
        sd = _state_dict(obj)
        replaced = 0
        for key, value in base_sd.items():
            if not key.startswith("dec."):
                continue
            if key in sd and sd[key].shape == value.shape:
                sd[key] = value
                replaced += 1
        if isinstance(obj, dict) and "model" in obj:
            obj["model"] = sd
            payload = obj
        else:
            payload = sd
        torch.save(payload, ckpt)
        swapped.append({"checkpoint": ckpt.name, "dec_keys": replaced})

    print(json.dumps({"swapped": swapped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
