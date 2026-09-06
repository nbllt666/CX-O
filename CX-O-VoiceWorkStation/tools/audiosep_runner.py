"""AudioSep 推理子进程 wrapper（供 workstation/services/vocal_separator.py 子进程调用）

引擎契约（以克隆实码为准，engines/AudioSep）：
- pipeline.build_audiosep(config_yaml, checkpoint_path, device)（pipeline.py L10）
- pipeline.separate_audio(model, audio_file, text, output_file, device, use_chunk)
  （pipeline.py L20；输入 librosa.load sr=32000 mono，输出 32kHz int16 wav）
- CLAP 文本编码器权重 checkpoint/music_speech_audioset_epoch_15_esc_89.98.pt
  在 CLAP_Encoder 构造时加载（models/clap_encoder.py L7），须位于引擎 checkpoint/ 下

调用方式（VocalSeparator 发起，cwd=引擎根）：
    python tools/audiosep_runner.py --engine-dir <AudioSep根> --checkpoint <.ckpt绝对路径>
        --input < vocals.wav绝对路径> --query-a "..." --query-b "..."
        --output-a <part_a.wav绝对路径> --output-b <part_b.wav绝对路径>
        [--device auto|cuda|cpu] [--config config/audiosep_base.yaml]

退出码：0=两路分离完成且产物存在；非 0=失败（stderr 含原因）。
路径全部以绝对路径传入/输出，本脚本对 CWD 免疫（rules-0 §三）。
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="AudioSep 双查询分离 wrapper")
    parser.add_argument("--engine-dir", required=True, help="AudioSep 引擎根目录（绝对路径）")
    parser.add_argument("--checkpoint", required=True, help="AudioSep checkpoint（.ckpt 绝对路径）")
    parser.add_argument("--config", default="config/audiosep_base.yaml",
                        help="模型配置 yaml（相对引擎根；默认 config/audiosep_base.yaml）")
    parser.add_argument("--input", required=True, help="输入人声 wav（绝对路径）")
    parser.add_argument("--query-a", required=True, help="A 声部文本查询")
    parser.add_argument("--query-b", required=True, help="B 声部文本查询")
    parser.add_argument("--output-a", required=True, help="A 声部输出 wav（绝对路径）")
    parser.add_argument("--output-b", required=True, help="B 声部输出 wav（绝对路径）")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    args = parser.parse_args()

    engine_dir = os.path.abspath(args.engine_dir)
    if not os.path.isdir(engine_dir):
        print(f"ERROR engine dir not found: {engine_dir}", file=sys.stderr)
        return 2
    # 引擎根入 sys.path 并 chdir：pipeline/utils/models 相对导入与 checkpoint/ 权重
    # 相对路径均以引擎根为基准（与官方 pipeline.py __main__ 用法一致）
    if engine_dir not in sys.path:
        sys.path.insert(0, engine_dir)
    os.chdir(engine_dir)

    for label, path in (("--checkpoint", args.checkpoint), ("--input", args.input)):
        if not os.path.isfile(path):
            print(f"ERROR {label} not found: {path}", file=sys.stderr)
            return 2

    try:
        import torch

        if args.device == "auto":
            # 与官方 pipeline.py __main__ 的探测方式一致（pipeline.py L48）
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = args.device

        from pipeline import build_audiosep, separate_audio

        config_path = (
            args.config if os.path.isabs(args.config)
            else os.path.join(engine_dir, args.config)
        )
        if not os.path.isfile(config_path):
            print(f"ERROR config yaml not found: {config_path}", file=sys.stderr)
            return 2

        model = build_audiosep(
            config_yaml=config_path,
            checkpoint_path=args.checkpoint,
            device=device,
        )
        separate_audio(model, args.input, args.query_a, args.output_a, device=device)
        separate_audio(model, args.input, args.query_b, args.output_b, device=device)
    except Exception as e:  # noqa: BLE001 - 子进程内异常统一转 stderr + 非0退出
        print(f"ERROR audiosep inference failed: {e}", file=sys.stderr)
        return 1

    for label, path in (("--output-a", args.output_a), ("--output-b", args.output_b)):
        if not os.path.isfile(path):
            print(f"ERROR output missing after separation: {label} {path}", file=sys.stderr)
            return 1

    print(f"AUDIOSEP_RUNNER_OK device={device}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
