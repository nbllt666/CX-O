"""MeloTTS 预训练底模转换（官方发布权重 → 本仓库符号表可用的预训练 G）。

背景：官方 basespeakers pretrained G.pth 的下载地址已失效（S3 NoSuchBucket），
引擎 `load_pretrain_model()` 只能返回 None，训练因此从零初始化——少量语料
必然只学到噪音。这里用官方发布的中文模型做「部分初始化」：

- enc_p.emb 按符号名迁移可对应的行（官方 112 符号 / 本仓库 219 符号），其余零初始化；
- tone/language 嵌入维度不同 → 前缀行复制、其余补零；
- emb_g（官方 256 说话人）只保留前 N 行（单说话人微调取 speaker 0）：随机初始化的
  说话人嵌入与官方权重不同分布，会让微调模型输出退化为噪音，必须迁移；
- 其余卷积/flow/解码器权重全部原样迁移。

本模块只依赖 torch + 标准库，供**引擎 python 子进程**调用（后端 python 无 torch）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch


def build_converted_base(
    released_ckpt: str,
    released_config: str,
    target_config: str,
    out_path: str,
) -> dict:
    released_obj = torch.load(released_ckpt, map_location="cpu")
    released_sd = released_obj["model"] if "model" in released_obj else released_obj
    released_symbols = json.loads(
        Path(released_config).read_text(encoding="utf-8")
    )["symbols"]
    target_cfg = json.loads(Path(target_config).read_text(encoding="utf-8"))
    target_symbols = target_cfg["symbols"]

    converted = dict(released_sd)

    src_emb = released_sd["enc_p.emb.weight"]
    dst_emb = torch.zeros(len(target_symbols), src_emb.shape[1])
    hit = 0
    for idx, sym in enumerate(target_symbols):
        if sym in released_symbols:
            dst_emb[idx] = src_emb[released_symbols.index(sym)]
            hit += 1
    converted["enc_p.emb.weight"] = dst_emb

    for key, target_len in (
        ("enc_p.tone_emb.weight", int(target_cfg.get("num_tones") or 16)),
        ("enc_p.language_emb.weight", int(target_cfg.get("num_languages") or 8)),
    ):
        src = released_sd[key]
        dst = torch.zeros(target_len, src.shape[1])
        n = min(target_len, src.shape[0])
        dst[:n] = src[:n]
        converted[key] = dst

    # 说话人嵌入：官方 256 说话人 → 微调目标 N 说话人（通常 1），取前 N 行。
    # 直接剔除会让 emb_g 随机初始化，整网条件分布错位 → 微调产物退化为噪音。
    src_spk = released_sd.get("emb_g.weight")
    n_speakers = int(target_cfg.get("n_speakers") or target_cfg.get("n_spk") or 1)
    if src_spk is not None:
        dst_spk = torch.zeros(n_speakers, src_spk.shape[1])
        n = min(n_speakers, src_spk.shape[0])
        dst_spk[:n] = src_spk[:n]
        converted["emb_g.weight"] = dst_spk

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model": converted, "iteration": 0, "optimizer": None}, out)
    return {
        "out": str(out),
        "emb_rows_total": len(target_symbols),
        "emb_rows_migrated": hit,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--released-ckpt", required=True)
    ap.add_argument("--released-config", required=True)
    ap.add_argument("--target-config", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    info = build_converted_base(
        args.released_ckpt, args.released_config, args.target_config, args.out
    )
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
