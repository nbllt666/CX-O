"""Orpheus Llama-3B 骨干权重转换脚本（HF -> FT checkpoint 格式）。

将 Orpheus 原始 HuggingFace checkpoint 中的 Llama-3B 骨干权重提取并转换为
FasterTransformer (FT) checkpoint 格式（FP16 1D 拆分权重文件）。

转换范围：
    - 提取 Llama backbone 权重（embedding + transformer layers + final norm）
    - 提取 Audio Head 权重（fc1/fc2）并导出为 C++ AudioHeadKernel 可加载的 .bin
      （输出到 <output>/audio_head/ 子目录，与 backbone 的 1-gpu/ 解耦）
    - 不包含 lm_head 的 backbone 转换（FT C++ 引擎只跑到 Llama 最后一层输出 hidden_states）

FT 权重格式说明（与 HF 的差异）：
    1. FT 用 1D 拆分权重文件：每个权重张量存为一个 .bin 文件（raw binary，row-major）。
       HF 用单个 .safetensors/.bin 打包所有权重。FT 拆分便于按张量并行（TP）切分加载。
    2. 文件命名：FT 沿用 HF 的层命名约定，但加上 .bin 后缀。
       例如 HF 的 model.layers.0.self_attn.q_proj.weight
            -> FT 的 model.layers.0.attention.wq.weight.bin
       （attention 子模块名映射：self_attn -> attention，q_proj -> wq 等）
    3. TP=1 时权重不拆分；TP>1 时沿 out_features 维度均匀切分到各 rank 文件。
    4. FT 还需一个 config 文件（config.ini）描述模型架构，供 C++ 引擎读取。

输出目录结构：
    <output_dir>/
      1-gpu/                                    # TP=1 子目录（FT 约定）
        model.embed_tokens.weight.bin
        model.layers.0.attention.wq.weight.bin
        model.layers.0.attention.wk.weight.bin
        model.layers.0.attention.wv.weight.bin
        model.layers.0.attention.wo.weight.bin
        model.layers.0.input_layernorm.weight.bin
        model.layers.0.post_attention_layernorm.weight.bin
        model.layers.0.mlp.gate_proj.weight.bin
        model.layers.0.mlp.up_proj.weight.bin
        model.layers.0.mlp.down_proj.weight.bin
        ... (其余层)
        model.norm.weight.bin
      config.ini                                # FT 架构配置

用法：
    python scripts/convert_checkpoint.py \\
        --input canopylabs/orpheus-multilingual-research-release \\
        --output checkpoints/orpheus-llama3b-ft \\
        --data-type fp16

    # 或用本地路径
    python scripts/convert_checkpoint.py \\
        --input /path/to/orpheus-3b-ft \\
        --output checkpoints/orpheus-llama3b-ft \\
        --data-type fp16
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional


# ============================================================================
# HF <-> FT 权重名映射表
# ============================================================================
# FT 的权重命名与 HF Llama 略有差异，主要在 attention 子模块名上：
#   HF:  model.layers.{i}.self_attn.q_proj.weight
#   FT:  model.layers.{i}.attention.wq.weight
# MLP 与 layernorm 命名一致，无需映射。
# ============================================================================
_ATTENTION_NAME_MAP = {
    "self_attn.q_proj": "attention.wq",
    "self_attn.k_proj": "attention.wk",
    "self_attn.v_proj": "attention.wv",
    "self_attn.o_proj": "attention.wo",
}


def _hf_to_ft_name(hf_name: str) -> str:
    """将 HF 权重名映射为 FT 权重名。

    Args:
        hf_name: HF 命名，如 "model.layers.0.self_attn.q_proj.weight"

    Returns:
        FT 命名，如 "model.layers.0.attention.wq.weight"

    非 attention 权重（embedding/layernorm/mlp/norm）直接原样返回。
    """
    for hf_key, ft_key in _ATTENTION_NAME_MAP.items():
        if hf_key in hf_name:
            return hf_name.replace(hf_key, ft_key)
    return hf_name


# ============================================================================
# 跳过的权重（不属于 Llama backbone）
# ============================================================================
# Orpheus 模型 = Llama-3B 骨干 + Audio Head。以下权重属于 Audio Head，不转换：
#   - lm_head.*           : LM head（FT 不做 LM head，只输出 hidden_states）
#   - audio_head.*        : Orpheus 自定义 Audio Head（Task 3 单独处理）
#   - snac.*              : SNAC 解码器权重（独立模块）
# 跳过原因：FT C++ 引擎只跑到 Llama 最后一层，输出 hidden_states 传回 Python，
# 由 Audio Head 消费。Audio Head 与 FT 解耦，便于快速迭代。
_SKIP_PREFIXES = ("lm_head", "audio_head", "snac")


def _should_skip(name: str) -> bool:
    """判断权重是否属于 Audio Head（跳过不转换）。"""
    return any(name.startswith(prefix) or name.startswith(f"model.{prefix}")
               for prefix in _SKIP_PREFIXES)


def _save_tensor_bin(tensor, filepath: Path, data_type: str) -> None:
    """将张量保存为 FT 1D .bin 文件（raw binary，row-major）。

    FT 约定：
        - 权重以 1D 连续内存布局存储（torch tensor.flatten() 后的 raw bytes）
        - FP16 用 float16，FP32 用 float32
        - 不含 shape 元数据（shape 由 config.ini 描述）

    Args:
        tensor: PyTorch 张量（HF 权重，可能为 fp32）。
        filepath: 输出 .bin 文件路径。
        data_type: "fp16" 或 "fp32"。
    """
    import torch

    # 转换数据类型（FP16 对应 Ampere Tensor Core 最优路径）。
    if data_type == "fp16":
        tensor = tensor.to(torch.float16)
    else:
        tensor = tensor.to(torch.float32)

    # 转为 CPU 连续内存（contiguous），flatten 为 1D 后写 raw bytes。
    tensor = tensor.detach().cpu().contiguous().flatten()
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(tensor.numpy().tobytes())


def _write_ft_config(output_dir: Path, config: object, data_type: str,
                     tensor_para_size: int) -> None:
    """写 FT config.ini 配置文件。

    FT C++ 引擎启动时读取此文件，获知模型架构（层数、隐藏维度、head 数等），
    据此分配 KV Cache 与 kernel 参数。

    Args:
        output_dir: FT checkpoint 根目录。
        config: HuggingFace AutoConfig 对象（含 architecture 字段）。
        data_type: "fp16" 或 "fp32"。
        tensor_para_size: 张量并行度。
    """
    config_path = output_dir / "config.ini"
    lines = [
        "[ft]",
        f"data_type={data_type}",
        f"tensor_para_size={tensor_para_size}",
        f"pipeline_para_size=1",
        f"vocab_size={getattr(config, 'vocab_size', 128256)}",
        f"hidden_size={getattr(config, 'hidden_size', 3072)}",
        f"num_layers={getattr(config, 'num_hidden_layers', 28)}",
        f"num_attention_heads={getattr(config, 'num_attention_heads', 24)}",
        f"num_key_value_heads={getattr(config, 'num_key_value_heads', getattr(config, 'num_attention_heads', 24))}",
        f"intermediate_size={getattr(config, 'intermediate_size', 8192)}",
        f"max_position_embeddings={getattr(config, 'max_position_embeddings', 4096)}",
        f"rms_norm_eps={getattr(config, 'rms_norm_eps', 1e-5)}",
        f"rope_theta={getattr(config, 'rope_theta', 500000.0)}",
        # FT 只跑到最后一层，不做 LM head（Orpheus Audio Head 在 Python 侧消费 hidden_states）
        "has_lm_head=false",
    ]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def convert_checkpoint(
    input_path: str,
    output_path: str,
    data_type: str = "fp16",
    tensor_para_size: int = 1,
) -> None:
    """执行 HF -> FT checkpoint 转换。

    流程：
        1. 用 transformers 加载 Orpheus 原始 HF checkpoint 的 state_dict 与 config。
        2. 遍历 state_dict，跳过 Audio Head 权重（lm_head / audio_head / snac）。
        3. 将剩余 Llama backbone 权重按 FT 命名约定保存为 1D .bin 文件。
        4. 写 config.ini 描述模型架构。

    Args:
        input_path: Orpheus 原始 checkpoint 路径（HF 仓库名或本地目录）。
        output_path: FT checkpoint 输出目录。
        data_type: "fp16" 或 "fp32"（默认 fp16，Ampere Tensor Core 最优）。
        tensor_para_size: 张量并行度（单卡=1，转换时不拆分权重）。
    """
    import torch
    from transformers import AutoConfig, AutoModelForCausalLM

    print(f"[convert] 输入: {input_path}")
    print(f"[convert] 输出: {output_path}")
    print(f"[convert] 数据类型: {data_type}, TP={tensor_para_size}")

    # 1. 加载 HF config 与模型权重。
    #   trust_remote_code=True：Orpheus 可能含自定义建模代码。
    print("[convert] 加载 HuggingFace config...")
    config = AutoConfig.from_pretrained(input_path, trust_remote_code=True)

    print("[convert] 加载 HuggingFace 模型权重（state_dict）...")
    # 用 torch_dtype=fp32 加载，转换时再按 data_type 降精度，避免 HF 自动量化丢精度。
    model = AutoModelForCausalLM.from_pretrained(
        input_path,
        torch_dtype=torch.float32,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    state_dict = model.state_dict()

    # 2. 构造输出目录：FT 约定 TP=N 时用 N-gpu/ 子目录。
    output_dir = Path(output_path)
    tp_dir = output_dir / f"{tensor_para_size}-gpu"
    tp_dir.mkdir(parents=True, exist_ok=True)

    # 3. 遍历 state_dict，跳过 Audio Head，保存 backbone 权重。
    converted = 0
    skipped = 0
    for hf_name, tensor in state_dict.items():
        if _should_skip(hf_name):
            skipped += 1
            print(f"  [skip] {hf_name}  (Audio Head / LM head，不转换)")
            continue

        # HF -> FT 命名映射（attention 子模块名转换）。
        ft_name = _hf_to_ft_name(hf_name)
        ft_filepath = tp_dir / f"{ft_name}.bin"

        # TP>1 时需沿 out_features 切分；TP=1 时直接保存整张量。
        if tensor_para_size > 1:
            _save_tensor_split(tensor, ft_filepath, data_type, tensor_para_size)
        else:
            _save_tensor_bin(tensor, ft_filepath, data_type)

        converted += 1
        print(f"  [ok]   {hf_name} -> {ft_name}.bin  shape={tuple(tensor.shape)}")

    print(f"[convert] 已转换 {converted} 个权重，跳过 {skipped} 个 Audio Head 权重")

    # 4. 写 FT config.ini。
    print("[convert] 写 config.ini...")
    _write_ft_config(output_dir, config, data_type, tensor_para_size)

    print(f"[convert] 完成！FT checkpoint 已保存到: {output_dir}")
    print(f"[convert] 目录结构:")
    print(f"          {output_dir}/")
    print(f"            {tensor_para_size}-gpu/  (权重 .bin 文件)")
    print(f"            config.ini       (架构配置)")


def _save_tensor_split(tensor, filepath: Path, data_type: str,
                       tensor_para_size: int) -> None:
    """TP>1 时沿 out_features 维度切分权重并分 rank 保存。

    FT 约定：TP=N 时权重按 out_features 均匀切分为 N 份，每份存为独立 .bin 文件，
    文件名加 .rank{i} 后缀。C++ 引擎各 rank 加载自己的分片。

    Args:
        tensor: 原始权重张量。
        filepath: 基础文件路径（不含 rank 后缀）。
        data_type: "fp16" 或 "fp32"。
        tensor_para_size: 张量并行度。
    """
    import torch

    if data_type == "fp16":
        tensor = tensor.to(torch.float16)
    else:
        tensor = tensor.to(torch.float32)

    tensor = tensor.detach().cpu().contiguous()
    # nn.Linear 权重 shape=[out_features, in_features]，沿 dim=0 切分。
    chunks = torch.chunk(tensor, tensor_para_size, dim=0)
    for rank, chunk in enumerate(chunks):
        rank_path = filepath.parent / f"{filepath.stem}.rank{rank}.bin"
        with open(rank_path, "wb") as f:
            f.write(chunk.flatten().numpy().tobytes())


# ============================================================================
# Audio Head 权重提取与导出
# ============================================================================
# 设计决策：
#   1. 为什么单独抽出此函数：Audio Head 与 Llama backbone 在同一 HF checkpoint 中，
#      但加载方式不同——backbone 由 FT C++ 引擎从 1-gpu/*.bin 加载，Audio Head
#      由 C++ AudioHeadKernel 或 Python 回退路径从 audio_head/*.bin 加载。
#      将 Audio Head 提取逻辑集中于此，避免在 backbone 转换流程中耦合。
#   2. 复用而非重复实现：
#      - 权重提取：复用 audio_head.weights_loader.AudioHeadWeightsLoader（已实现
#        audio_head./lm_head. 前缀过滤、目录/单文件加载、safetensors/.bin 支持）
#      - .bin 导出：复用 audio_head.audio_head_cpp.export_audio_head_weights_to_bin
#        （已实现 FP16 转换 + 转置 + 写盘，是 .bin 格式的契约源）
#      本函数仅负责"提取 -> 装入 AudioHead 实例 -> 调用导出"的编排。
#
# .bin 格式契约（与 ft_engine/decoding_cpp/audio_head_kernel.h:load_weights 一致）：
#   audio_head/fc1.bin      : FP16, shape [hidden_dim, intermediate_dim]（行主序）
#                            = PyTorch fc1.weight [intermediate, hidden] 的转置
#   audio_head/fc2.bin      : FP16, shape [intermediate_dim, num_codebooks*snac_vocab_size]
#                            = PyTorch fc2.weight 的转置
#   audio_head/fc1_bias.bin : FP16, shape [intermediate_dim]（可选）
#   audio_head/fc2_bias.bin : FP16, shape [num_codebooks*snac_vocab_size]（可选）
#   存转置的原因：C++ GEMM 直接做 X @ W（行主序），W 按 [in, out] 存储省去运行时转置。
# ============================================================================
def extract_and_export_audio_head_weights(
    orpheus_checkpoint_path: str,
    output_dir: str,
    hidden_dim: int = 3072,
    intermediate_dim: int = 1024,
    num_codebooks: int = 4,
    snac_vocab_size: int = 4096,
) -> str:
    """从 Orpheus 原始 checkpoint 提取 Audio Head 权重并导出为 C++ 侧 .bin 格式。

    流程：
        1. 用 AudioHeadWeightsLoader 从 HF checkpoint 提取 audio_head.* 权重。
        2. 构造临时 PyTorch AudioHead 实例并加载提取的权重。
        3. 调用 export_audio_head_weights_to_bin 导出到 output_dir/audio_head/。
        4. 返回 audio_head/ 子目录路径。

    Args:
        orpheus_checkpoint_path: Orpheus 原始 checkpoint 路径（HF 目录或单文件）。
        output_dir: FT checkpoint 根目录（与 backbone 的 1-gpu/ 同级）。
        hidden_dim: Llama 隐藏维度（Llama-3B=3072）。
        intermediate_dim: Audio Head 中间层维度（默认 1024）。
        num_codebooks: SNAC codebook 数量（默认 4）。
        snac_vocab_size: SNAC 码本大小（默认 4096）。

    Returns:
        audio_head 目录的绝对路径（<output_dir>/audio_head/）。

    Raises:
        FileNotFoundError: checkpoint 路径不存在。
        RuntimeError: checkpoint 中未找到 audio_head 权重。
    """
    # 延迟导入，避免未安装 torch 的环境加载本模块时失败。
    # 同时把项目根目录加入 sys.path：本脚本可能以 `python scripts/convert_checkpoint.py`
    # 方式运行（sys.path[0]=scripts/），需补上项目根以 import audio_head 包。
    _project_root = str(Path(__file__).resolve().parent.parent)
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    from audio_head import AudioHead, AudioHeadWeightsLoader
    from audio_head.audio_head_cpp import export_audio_head_weights_to_bin

    print("[audio_head] 从 Orpheus checkpoint 提取 Audio Head 权重...")
    print(f"  checkpoint: {orpheus_checkpoint_path}")
    print(f"  维度: hidden={hidden_dim}, intermediate={intermediate_dim}, "
          f"codebooks={num_codebooks}, snac_vocab={snac_vocab_size}")

    # 1. 提取 audio_head 权重（复用 weights_loader 的过滤逻辑）。
    #    提取后键名为去掉前缀的模块路径（如 'fc1.weight'），可直接 load_state_dict。
    extracted = AudioHeadWeightsLoader.extract_from_hf_checkpoint(
        orpheus_checkpoint_path
    )
    print(f"  [audio_head] 已提取 {len(extracted)} 个权重:")
    for key, tensor in extracted.items():
        print(f"    - {key}  shape={tuple(tensor.shape)}")

    # 2. 构造临时 AudioHead 实例并加载权重。
    #    gpu_id=99 强制 CPU 路径（权重导出无需 GPU，且保证无 GPU 环境可运行）。
    audio_head = AudioHead(
        hidden_dim=hidden_dim,
        intermediate_dim=intermediate_dim,
        num_codebooks=num_codebooks,
        snac_vocab_size=snac_vocab_size,
        gpu_id=99,  # CPU：仅做权重搬运与导出，无需 GPU
    )
    # strict=True：提取的键必须与 AudioHead 模块完全对应，
    # 多余/缺失均报错（避免静默加载不完整的 Audio Head 权重）。
    audio_head.load_state_dict(extracted, strict=True)

    # 3. 导出为 .bin（FP16）到 output_dir/audio_head/ 子目录。
    #    复用 export_audio_head_weights_to_bin：它是 .bin 格式契约的源，
    #    C++ AudioHeadKernel.load_weights 与 Python load_bin_into_audio_head
    #    均按此导出格式读取。
    audio_head_dir = Path(output_dir) / "audio_head"
    audio_head_dir.mkdir(parents=True, exist_ok=True)
    export_audio_head_weights_to_bin(audio_head, str(audio_head_dir))

    print(f"  [audio_head] 已导出到: {audio_head_dir}")
    print(f"    fc1.bin      : [hidden_dim={hidden_dim}, intermediate_dim={intermediate_dim}]")
    print(f"    fc2.bin      : [intermediate_dim={intermediate_dim}, "
          f"num_codebooks*snac_vocab={num_codebooks * snac_vocab_size}]")
    print(f"    fc1_bias.bin : [intermediate_dim={intermediate_dim}]")
    print(f"    fc2_bias.bin : [num_codebooks*snac_vocab={num_codebooks * snac_vocab_size}]")

    return str(audio_head_dir)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Orpheus Llama-3B 骨干权重转换（HF -> FT checkpoint 格式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Orpheus 原始 checkpoint 路径（HF 仓库名如 "
             "canopylabs/orpheus-multilingual-research-release，或本地目录）",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        required=True,
        help="FT checkpoint 输出路径（如 checkpoints/orpheus-llama3b-ft）",
    )
    parser.add_argument(
        "--data-type", "-d",
        type=str,
        default="fp16",
        choices=["fp16", "fp32"],
        help="权重数据类型（默认 fp16，Ampere FP16 Tensor Core 最优）",
    )
    parser.add_argument(
        "--tensor-para-size", "-t",
        type=int,
        default=1,
        help="张量并行度（默认 1，单卡物理隔离下无需 TP）",
    )
    # --extract-audio-head / --no-extract-audio-head：
    # 默认开启提取 Audio Head 权重（与 backbone 转换解耦但同流程产出）。
    # 用 store_true/store_false 对兼容老版本 argparse（无 BooleanOptionalAction）。
    parser.add_argument(
        "--extract-audio-head",
        dest="extract_audio_head",
        action="store_true",
        default=True,
        help="提取 Audio Head 权重并导出到 audio_head/ 子目录（默认开启）",
    )
    parser.add_argument(
        "--no-extract-audio-head",
        dest="extract_audio_head",
        action="store_false",
        help="不提取 Audio Head 权重（仅转换 Llama backbone）",
    )
    return parser.parse_args()


def main() -> None:
    """脚本入口。"""
    args = parse_args()

    # 延迟导入 transformers/torch，仅在真正转换时检查依赖。
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError as e:
        sys.stderr.write(
            "[convert_checkpoint] 缺少依赖，请先安装：\n"
            "    pip install torch transformers\n"
            f"原始错误: {e}\n"
        )
        raise SystemExit(1)

    convert_checkpoint(
        input_path=args.input,
        output_path=args.output,
        data_type=args.data_type,
        tensor_para_size=args.tensor_para_size,
    )

    # 提取 Audio Head 权重（默认开启，与 backbone 转换同流程产出）。
    # 输出到 <output>/audio_head/ 子目录，供 C++ AudioHeadKernel.load_weights 读取。
    if args.extract_audio_head:
        extract_and_export_audio_head_weights(
            orpheus_checkpoint_path=args.input,
            output_dir=args.output,
        )
        print(f"[convert] Audio Head 权重已导出到: {args.output}/audio_head/")


if __name__ == "__main__":
    main()
