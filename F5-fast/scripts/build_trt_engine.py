#!/usr/bin/env python3
"""
TensorRT-LLM 引擎构建脚本
为 F5-TTS 模型构建适配当前 GPU 的 TensorRT 引擎
"""

import argparse
import json
import os
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import torch

from tensorrt_llm import str_dtype_to_torch
from tensorrt_llm.mapping import Mapping
from tensorrt_llm.models.convert_utils import split, split_matrix_tp


def get_gpu_info():
    """获取 GPU 信息"""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用")
    
    device = torch.cuda.current_device()
    gpu_name = torch.cuda.get_device_name(device)
    compute_capability = torch.cuda.get_device_capability(device)
    total_memory = torch.cuda.get_device_properties(device).total_memory / (1024**3)
    
    return {
        "name": gpu_name,
        "compute_capability": f"{compute_capability[0]}{compute_capability[1]}",
        "sm": compute_capability[0] * 10 + compute_capability[1],
        "memory_gb": round(total_memory, 1),
        "cluster_key": gpu_name.replace(" ", "-")
    }


def split_q_tp(v, n_head, n_hidden, tensor_parallel, rank):
    split_v = split(v, tensor_parallel, rank, dim=1)
    return split_v.contiguous()


def split_q_bias_tp(v, n_head, n_hidden, tensor_parallel, rank):
    split_v = split(v, tensor_parallel, rank, dim=0)
    return split_v.contiguous()


FACEBOOK_DIT_NAME_MAPPING = {
    "^time_embed.time_mlp.0.weight$": "time_embed.mlp1.weight",
    "^time_embed.time_mlp.0.bias$": "time_embed.mlp1.bias",
    "^time_embed.time_mlp.2.weight$": "time_embed.mlp2.weight",
    "^time_embed.time_mlp.2.bias$": "time_embed.mlp2.bias",
    "^input_embed.conv_pos_embed.conv1d.0.weight$": "input_embed.conv_pos_embed.conv1d1.weight",
    "^input_embed.conv_pos_embed.conv1d.0.bias$": "input_embed.conv_pos_embed.conv1d1.bias",
    "^input_embed.conv_pos_embed.conv1d.2.weight$": "input_embed.conv_pos_embed.conv1d2.weight",
    "^input_embed.conv_pos_embed.conv1d.2.bias$": "input_embed.conv_pos_embed.conv1d2.bias",
    "^transformer_blocks.0.attn.to_out.0.weight$": "transformer_blocks.0.attn.to_out.weight",
    "^transformer_blocks.0.attn.to_out.0.bias$": "transformer_blocks.0.attn.to_out.bias",
    "^transformer_blocks.1.attn.to_out.0.weight$": "transformer_blocks.1.attn.to_out.weight",
    "^transformer_blocks.1.attn.to_out.0.bias$": "transformer_blocks.1.attn.to_out.bias",
    "^transformer_blocks.2.attn.to_out.0.weight$": "transformer_blocks.2.attn.to_out.weight",
    "^transformer_blocks.2.attn.to_out.0.bias$": "transformer_blocks.2.attn.to_out.bias",
    "^transformer_blocks.3.attn.to_out.0.weight$": "transformer_blocks.3.attn.to_out.weight",
    "^transformer_blocks.3.attn.to_out.0.bias$": "transformer_blocks.3.attn.to_out.bias",
    "^transformer_blocks.4.attn.to_out.0.weight$": "transformer_blocks.4.attn.to_out.weight",
    "^transformer_blocks.4.attn.to_out.0.bias$": "transformer_blocks.4.attn.to_out.bias",
    "^transformer_blocks.5.attn.to_out.0.weight$": "transformer_blocks.5.attn.to_out.weight",
    "^transformer_blocks.5.attn.to_out.0.bias$": "transformer_blocks.5.attn.to_out.bias",
    "^transformer_blocks.6.attn.to_out.0.weight$": "transformer_blocks.6.attn.to_out.weight",
    "^transformer_blocks.6.attn.to_out.0.bias$": "transformer_blocks.6.attn.to_out.bias",
    "^transformer_blocks.7.attn.to_out.0.weight$": "transformer_blocks.7.attn.to_out.weight",
    "^transformer_blocks.7.attn.to_out.0.bias$": "transformer_blocks.7.attn.to_out.bias",
    "^transformer_blocks.8.attn.to_out.0.weight$": "transformer_blocks.8.attn.to_out.weight",
    "^transformer_blocks.8.attn.to_out.0.bias$": "transformer_blocks.8.attn.to_out.bias",
    "^transformer_blocks.9.attn.to_out.0.weight$": "transformer_blocks.9.attn.to_out.weight",
    "^transformer_blocks.9.attn.to_out.0.bias$": "transformer_blocks.9.attn.to_out.bias",
    "^transformer_blocks.10.attn.to_out.0.weight$": "transformer_blocks.10.attn.to_out.weight",
    "^transformer_blocks.10.attn.to_out.0.bias$": "transformer_blocks.10.attn.to_out.bias",
    "^transformer_blocks.11.attn.to_out.0.weight$": "transformer_blocks.11.attn.to_out.weight",
    "^transformer_blocks.11.attn.to_out.0.bias$": "transformer_blocks.11.attn.to_out.bias",
    "^transformer_blocks.12.attn.to_out.0.weight$": "transformer_blocks.12.attn.to_out.weight",
    "^transformer_blocks.12.attn.to_out.0.bias$": "transformer_blocks.12.attn.to_out.bias",
    "^transformer_blocks.13.attn.to_out.0.weight$": "transformer_blocks.13.attn.to_out.weight",
    "^transformer_blocks.13.attn.to_out.0.bias$": "transformer_blocks.13.attn.to_out.bias",
    "^transformer_blocks.14.attn.to_out.0.weight$": "transformer_blocks.14.attn.to_out.weight",
    "^transformer_blocks.14.attn.to_out.0.bias$": "transformer_blocks.14.attn.to_out.bias",
    "^transformer_blocks.15.attn.to_out.0.weight$": "transformer_blocks.15.attn.to_out.weight",
    "^transformer_blocks.15.attn.to_out.0.bias$": "transformer_blocks.15.attn.to_out.bias",
    "^transformer_blocks.16.attn.to_out.0.weight$": "transformer_blocks.16.attn.to_out.weight",
    "^transformer_blocks.16.attn.to_out.0.bias$": "transformer_blocks.16.attn.to_out.bias",
    "^transformer_blocks.17.attn.to_out.0.weight$": "transformer_blocks.17.attn.to_out.weight",
    "^transformer_blocks.17.attn.to_out.0.bias$": "transformer_blocks.17.attn.to_out.bias",
    "^transformer_blocks.18.attn.to_out.0.weight$": "transformer_blocks.18.attn.to_out.weight",
    "^transformer_blocks.18.attn.to_out.0.bias$": "transformer_blocks.18.attn.to_out.bias",
    "^transformer_blocks.19.attn.to_out.0.weight$": "transformer_blocks.19.attn.to_out.weight",
    "^transformer_blocks.19.attn.to_out.0.bias$": "transformer_blocks.19.attn.to_out.bias",
    "^transformer_blocks.20.attn.to_out.0.weight$": "transformer_blocks.20.attn.to_out.weight",
    "^transformer_blocks.20.attn.to_out.0.bias$": "transformer_blocks.20.attn.to_out.bias",
    "^transformer_blocks.21.attn.to_out.0.weight$": "transformer_blocks.21.attn.to_out.weight",
    "^transformer_blocks.21.attn.to_out.0.bias$": "transformer_blocks.21.attn.to_out.bias",
    "^transformer_blocks.0.ff.ff.0.0.weight$": "transformer_blocks.0.ff.project_in.weight",
    "^transformer_blocks.0.ff.ff.0.0.bias$": "transformer_blocks.0.ff.project_in.bias",
    "^transformer_blocks.0.ff.ff.2.weight$": "transformer_blocks.0.ff.ff.weight",
    "^transformer_blocks.0.ff.ff.2.bias$": "transformer_blocks.0.ff.ff.bias",
    "^transformer_blocks.1.ff.ff.0.0.weight$": "transformer_blocks.1.ff.project_in.weight",
    "^transformer_blocks.1.ff.ff.0.0.bias$": "transformer_blocks.1.ff.project_in.bias",
    "^transformer_blocks.1.ff.ff.2.weight$": "transformer_blocks.1.ff.ff.weight",
    "^transformer_blocks.1.ff.ff.2.bias$": "transformer_blocks.1.ff.ff.bias",
    "^transformer_blocks.2.ff.ff.0.0.weight$": "transformer_blocks.2.ff.project_in.weight",
    "^transformer_blocks.2.ff.ff.0.0.bias$": "transformer_blocks.2.ff.project_in.bias",
    "^transformer_blocks.2.ff.ff.2.weight$": "transformer_blocks.2.ff.ff.weight",
    "^transformer_blocks.2.ff.ff.2.bias$": "transformer_blocks.2.ff.ff.bias",
    "^transformer_blocks.3.ff.ff.0.0.weight$": "transformer_blocks.3.ff.project_in.weight",
    "^transformer_blocks.3.ff.ff.0.0.bias$": "transformer_blocks.3.ff.project_in.bias",
    "^transformer_blocks.3.ff.ff.2.weight$": "transformer_blocks.3.ff.ff.weight",
    "^transformer_blocks.3.ff.ff.2.bias$": "transformer_blocks.3.ff.ff.bias",
    "^transformer_blocks.4.ff.ff.0.0.weight$": "transformer_blocks.4.ff.project_in.weight",
    "^transformer_blocks.4.ff.ff.0.0.bias$": "transformer_blocks.4.ff.project_in.bias",
    "^transformer_blocks.4.ff.ff.2.weight$": "transformer_blocks.4.ff.ff.weight",
    "^transformer_blocks.4.ff.ff.2.bias$": "transformer_blocks.4.ff.ff.bias",
    "^transformer_blocks.5.ff.ff.0.0.weight$": "transformer_blocks.5.ff.project_in.weight",
    "^transformer_blocks.5.ff.ff.0.0.bias$": "transformer_blocks.5.ff.project_in.bias",
    "^transformer_blocks.5.ff.ff.2.weight$": "transformer_blocks.5.ff.ff.weight",
    "^transformer_blocks.5.ff.ff.2.bias$": "transformer_blocks.5.ff.ff.bias",
    "^transformer_blocks.6.ff.ff.0.0.weight$": "transformer_blocks.6.ff.project_in.weight",
    "^transformer_blocks.6.ff.ff.0.0.bias$": "transformer_blocks.6.ff.project_in.bias",
    "^transformer_blocks.6.ff.ff.2.weight$": "transformer_blocks.6.ff.ff.weight",
    "^transformer_blocks.6.ff.ff.2.bias$": "transformer_blocks.6.ff.ff.bias",
    "^transformer_blocks.7.ff.ff.0.0.weight$": "transformer_blocks.7.ff.project_in.weight",
    "^transformer_blocks.7.ff.ff.0.0.bias$": "transformer_blocks.7.ff.project_in.bias",
    "^transformer_blocks.7.ff.ff.2.weight$": "transformer_blocks.7.ff.ff.weight",
    "^transformer_blocks.7.ff.ff.2.bias$": "transformer_blocks.7.ff.ff.bias",
    "^transformer_blocks.8.ff.ff.0.0.weight$": "transformer_blocks.8.ff.project_in.weight",
    "^transformer_blocks.8.ff.ff.0.0.bias$": "transformer_blocks.8.ff.project_in.bias",
    "^transformer_blocks.8.ff.ff.2.weight$": "transformer_blocks.8.ff.ff.weight",
    "^transformer_blocks.8.ff.ff.2.bias$": "transformer_blocks.8.ff.ff.bias",
    "^transformer_blocks.9.ff.ff.0.0.weight$": "transformer_blocks.9.ff.project_in.weight",
    "^transformer_blocks.9.ff.ff.0.0.bias$": "transformer_blocks.9.ff.project_in.bias",
    "^transformer_blocks.9.ff.ff.2.weight$": "transformer_blocks.9.ff.ff.weight",
    "^transformer_blocks.9.ff.ff.2.bias$": "transformer_blocks.9.ff.ff.bias",
    "^transformer_blocks.10.ff.ff.0.0.weight$": "transformer_blocks.10.ff.project_in.weight",
    "^transformer_blocks.10.ff.ff.0.0.bias$": "transformer_blocks.10.ff.project_in.bias",
    "^transformer_blocks.10.ff.ff.2.weight$": "transformer_blocks.10.ff.ff.weight",
    "^transformer_blocks.10.ff.ff.2.bias$": "transformer_blocks.10.ff.ff.bias",
    "^transformer_blocks.11.ff.ff.0.0.weight$": "transformer_blocks.11.ff.project_in.weight",
    "^transformer_blocks.11.ff.ff.0.0.bias$": "transformer_blocks.11.ff.project_in.bias",
    "^transformer_blocks.11.ff.ff.2.weight$": "transformer_blocks.11.ff.ff.weight",
    "^transformer_blocks.11.ff.ff.2.bias$": "transformer_blocks.11.ff.ff.bias",
    "^transformer_blocks.12.ff.ff.0.0.weight$": "transformer_blocks.12.ff.project_in.weight",
    "^transformer_blocks.12.ff.ff.0.0.bias$": "transformer_blocks.12.ff.project_in.bias",
    "^transformer_blocks.12.ff.ff.2.weight$": "transformer_blocks.12.ff.ff.weight",
    "^transformer_blocks.12.ff.ff.2.bias$": "transformer_blocks.12.ff.ff.bias",
    "^transformer_blocks.13.ff.ff.0.0.weight$": "transformer_blocks.13.ff.project_in.weight",
    "^transformer_blocks.13.ff.ff.0.0.bias$": "transformer_blocks.13.ff.project_in.bias",
    "^transformer_blocks.13.ff.ff.2.weight$": "transformer_blocks.13.ff.ff.weight",
    "^transformer_blocks.13.ff.ff.2.bias$": "transformer_blocks.13.ff.ff.bias",
    "^transformer_blocks.14.ff.ff.0.0.weight$": "transformer_blocks.14.ff.project_in.weight",
    "^transformer_blocks.14.ff.ff.0.0.bias$": "transformer_blocks.14.ff.project_in.bias",
    "^transformer_blocks.14.ff.ff.2.weight$": "transformer_blocks.14.ff.ff.weight",
    "^transformer_blocks.14.ff.ff.2.bias$": "transformer_blocks.14.ff.ff.bias",
    "^transformer_blocks.15.ff.ff.0.0.weight$": "transformer_blocks.15.ff.project_in.weight",
    "^transformer_blocks.15.ff.ff.0.0.bias$": "transformer_blocks.15.ff.project_in.bias",
    "^transformer_blocks.15.ff.ff.2.weight$": "transformer_blocks.15.ff.ff.weight",
    "^transformer_blocks.15.ff.ff.2.bias$": "transformer_blocks.15.ff.ff.bias",
    "^transformer_blocks.16.ff.ff.0.0.weight$": "transformer_blocks.16.ff.project_in.weight",
    "^transformer_blocks.16.ff.ff.0.0.bias$": "transformer_blocks.16.ff.project_in.bias",
    "^transformer_blocks.16.ff.ff.2.weight$": "transformer_blocks.16.ff.ff.weight",
    "^transformer_blocks.16.ff.ff.2.bias$": "transformer_blocks.16.ff.ff.bias",
    "^transformer_blocks.17.ff.ff.0.0.weight$": "transformer_blocks.17.ff.project_in.weight",
    "^transformer_blocks.17.ff.ff.0.0.bias$": "transformer_blocks.17.ff.project_in.bias",
    "^transformer_blocks.17.ff.ff.2.weight$": "transformer_blocks.17.ff.ff.weight",
    "^transformer_blocks.17.ff.ff.2.bias$": "transformer_blocks.17.ff.ff.bias",
    "^transformer_blocks.18.ff.ff.0.0.weight$": "transformer_blocks.18.ff.project_in.weight",
    "^transformer_blocks.18.ff.ff.0.0.bias$": "transformer_blocks.18.ff.project_in.bias",
    "^transformer_blocks.18.ff.ff.2.weight$": "transformer_blocks.18.ff.ff.weight",
    "^transformer_blocks.18.ff.ff.2.bias$": "transformer_blocks.18.ff.ff.bias",
    "^transformer_blocks.19.ff.ff.0.0.weight$": "transformer_blocks.19.ff.project_in.weight",
    "^transformer_blocks.19.ff.ff.0.0.bias$": "transformer_blocks.19.ff.project_in.bias",
    "^transformer_blocks.19.ff.ff.2.weight$": "transformer_blocks.19.ff.ff.weight",
    "^transformer_blocks.19.ff.ff.2.bias$": "transformer_blocks.19.ff.ff.bias",
    "^transformer_blocks.20.ff.ff.0.0.weight$": "transformer_blocks.20.ff.project_in.weight",
    "^transformer_blocks.20.ff.ff.0.0.bias$": "transformer_blocks.20.ff.project_in.bias",
    "^transformer_blocks.20.ff.ff.2.weight$": "transformer_blocks.20.ff.ff.weight",
    "^transformer_blocks.20.ff.ff.2.bias$": "transformer_blocks.20.ff.ff.bias",
    "^transformer_blocks.21.ff.ff.0.0.weight$": "transformer_blocks.21.ff.project_in.weight",
    "^transformer_blocks.21.ff.ff.0.0.bias$": "transformer_blocks.21.ff.project_in.bias",
    "^transformer_blocks.21.ff.ff.2.weight$": "transformer_blocks.21.ff.ff.weight",
    "^transformer_blocks.21.ff.ff.2.bias$": "transformer_blocks.21.ff.ff.bias",
}


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model_name",
        type=str,
        default="F5TTS_Base",
        choices=["F5TTS_Base"],
    )
    parser.add_argument("--timm_ckpt", type=str, default="/models/F5TTS_Base/model_1200000.pt")
    parser.add_argument(
        "--output_dir", type=str, default="/engines_new", 
        help="The path to save the TensorRT-LLM engine"
    )
    parser.add_argument("--hidden_size", type=int, default=1024)
    parser.add_argument("--depth", type=int, default=22)
    parser.add_argument("--num_heads", type=int, default=16)
    parser.add_argument("--cfg_scale", type=float, default=4.0)
    parser.add_argument("--tp_size", type=int, default=1)
    parser.add_argument("--cp_size", type=int, default=1)
    parser.add_argument("--pp_size", type=int, default=1)
    parser.add_argument("--dtype", type=str, default="float16", choices=["float32", "bfloat16", "float16"])
    parser.add_argument("--fp8_linear", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max_input_len", type=int, default=1024)
    parser.add_argument("--max_seq_len", type=int, default=2048)
    parser.add_argument("--max_batch_size", type=int, default=8)
    parser.add_argument("--opt_batch_size", type=int, default=2)
    parser.add_argument("--gpus_per_node", type=int, default=1)
    return parser.parse_args()


def convert_timm_dit(args, mapping, dtype="float16"):
    import safetensors.torch
    
    weights = {}
    tik = time.time()
    torch_dtype = str_dtype_to_torch(dtype)
    tensor_parallel = mapping.tp_size

    print(f"Loading model from {args.timm_ckpt}...")
    model_params = dict(torch.load(args.timm_ckpt, map_location="cpu"))
    model_params = {
        k: v for k, v in model_params["ema_model_state_dict"].items() if k.startswith("ema_model.transformer")
    }
    prefix = "ema_model.transformer."
    model_params = {key[len(prefix) :] if key.startswith(prefix) else key: value for key, value in model_params.items()}

    timm_to_trtllm_name = FACEBOOK_DIT_NAME_MAPPING

    def get_trtllm_name(timm_name):
        for k, v in timm_to_trtllm_name.items():
            m = re.match(k, timm_name)
            if m is not None:
                if "*" in v:
                    v = v.replace("*", m.groups()[0])
                return v
        return timm_name

    weights = dict()
    for name, param in model_params.items():
        if name == "input_embed.conv_pos_embed.conv1d.0.weight" or name == "input_embed.conv_pos_embed.conv1d.2.weight":
            weights[get_trtllm_name(name)] = param.contiguous().to(torch_dtype).unsqueeze(-1)
        else:
            weights[get_trtllm_name(name)] = param.contiguous().to(torch_dtype)

    assert len(weights) == len(model_params)

    new_prefix = ""
    weights = {new_prefix + key: value for key, value in weights.items()}
    import math

    scale_factor = math.pow(64, -0.25)
    for k, v in weights.items():
        if re.match("^transformer_blocks.*.attn.to_k.weight$", k):
            weights[k] *= scale_factor
            weights[k] = split_q_tp(v, args.num_heads, args.hidden_size, tensor_parallel, mapping.tp_rank)

        elif re.match("^transformer_blocks.*.attn.to_k.bias$", k):
            weights[k] *= scale_factor
            weights[k] = split_q_bias_tp(v, args.num_heads, args.hidden_size, tensor_parallel, mapping.tp_rank)

        elif re.match("^transformer_blocks.*.attn.to_q.weight$", k):
            weights[k] = split_q_tp(v, args.num_heads, args.hidden_size, tensor_parallel, mapping.tp_rank)
            weights[k] *= scale_factor

        elif re.match("^transformer_blocks.*.attn.to_q.bias$", k):
            weights[k] = split_q_bias_tp(v, args.num_heads, args.hidden_size, tensor_parallel, mapping.tp_rank)
            weights[k] *= scale_factor

        elif re.match("^transformer_blocks.*.attn.to_v.weight$", k):
            weights[k] = split_q_tp(v, args.num_heads, args.hidden_size, tensor_parallel, mapping.tp_rank)

        elif re.match("^transformer_blocks.*.attn.to_v.bias$", k):
            weights[k] = split_q_bias_tp(v, args.num_heads, args.hidden_size, tensor_parallel, mapping.tp_rank)

        elif re.match("^transformer_blocks.*.attn.to_out.weight$", k):
            weights[k] = split_matrix_tp(v, tensor_parallel, mapping.tp_rank, dim=1)

    tok = time.time()
    t = time.strftime("%H:%M:%S", time.gmtime(tok - tik))
    print(f"Weights loaded. Total time: {t}")
    return weights


def save_checkpoint_config(args, gpu_info):
    """保存 checkpoint 配置"""
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)
    
    config = {
        "architecture": "F5TTS",
        "dtype": args.dtype,
        "hidden_size": 1024,
        "num_hidden_layers": 22,
        "num_attention_heads": 16,
        "dim_head": 64,
        "dropout": 0.1,
        "ff_mult": 2,
        "mel_dim": 100,
        "text_num_embeds": 256,
        "text_dim": 512,
        "conv_layers": 4,
        "long_skip_connection": False,
        "mapping": {
            "world_size": args.cp_size * args.tp_size * args.pp_size,
            "cp_size": args.cp_size,
            "tp_size": args.tp_size,
            "pp_size": args.pp_size,
        },
    }
    if args.fp8_linear:
        config["quantization"] = {
            "quant_algo": "FP8",
        }

    with open(os.path.join(args.output_dir, "config.json"), "w") as f:
        json.dump(config, f, indent=4)
    
    print(f"Checkpoint config saved to {args.output_dir}/config.json")


def covert_and_save(args, rank, gpu_info):
    import safetensors.torch
    
    if rank == 0:
        save_checkpoint_config(args, gpu_info)

    mapping = Mapping(
        world_size=args.cp_size * args.tp_size * args.pp_size,
        rank=rank,
        cp_size=args.cp_size,
        tp_size=args.tp_size,
        pp_size=args.pp_size,
    )

    weights = convert_timm_dit(args, mapping, dtype=args.dtype)

    safetensors.torch.save_file(weights, os.path.join(args.output_dir, f"rank{rank}.safetensors"))
    print(f"Checkpoint saved to {args.output_dir}/rank{rank}.safetensors")


def build_engine(args, gpu_info):
    """构建 TensorRT 引擎"""
    from tensorrt_llm.builder import Builder, BuilderConfig
    from tensorrt_llm.network import net_guard
    from tensorrt_llm.models import F5TTS as F5TTSModel
    
    print("\n" + "=" * 60)
    print("Building TensorRT Engine")
    print("=" * 60)
    print(f"GPU: {gpu_info['name']}")
    print(f"Compute Capability: SM {gpu_info['compute_capability']}")
    print(f"Memory: {gpu_info['memory_gb']} GB")
    print(f"Cluster Key: {gpu_info['cluster_key']}")
    print("=" * 60 + "\n")
    
    builder = Builder()
    
    build_config = builder.create_build_config(
        max_input_len=args.max_input_len,
        max_seq_len=args.max_seq_len,
        max_batch_size=args.max_batch_size,
        opt_batch_size=args.opt_batch_size,
    )
    
    build_config.max_num_tokens = args.max_seq_len * args.max_batch_size
    build_config.strongly_typed = True
    build_config.plugin_config.gpt_attention_plugin = "auto"
    build_config.plugin_config.bert_attention_plugin = "auto"
    build_config.plugin_config.gemm_plugin = "auto"
    
    builder_config = BuilderConfig(
        name="F5TTS",
        precision=args.dtype,
        tensor_parallel=args.tp_size,
        pipeline_parallel=args.pp_size,
        gpus_per_node=args.gpus_per_node,
        max_batch_size=args.max_batch_size,
        max_input_len=args.max_input_len,
        max_seq_len=args.max_seq_len,
    )
    
    builder_config.set_cluster_key(gpu_info['cluster_key'])
    
    print("Building engine...")
    tik = time.time()
    
    model = F5TTSModel.from_checkpoint(
        checkpoint_dir=args.output_dir,
        rank=0,
    )
    
    engine = builder.build(model, builder_config)
    
    tok = time.time()
    t = time.strftime("%H:%M:%S", time.gmtime(tok - tik))
    print(f"Engine built in {t}")
    
    engine_dir = args.output_dir
    engine.save(engine_dir)
    print(f"Engine saved to {engine_dir}")
    
    return engine_dir


def execute(workers, func, args, gpu_info):
    if workers == 1:
        for rank, f in enumerate(func):
            f(args, rank, gpu_info)
    else:
        with ThreadPoolExecutor(max_workers=workers) as p:
            futures = [p.submit(f, args, rank, gpu_info) for rank, f in enumerate(func)]
            exceptions = []
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    traceback.print_exc()
                    exceptions.append(e)
            assert len(exceptions) == 0, "Checkpoint conversion failed, please check error log."


def main():
    args = parse_arguments()
    
    print("\n" + "=" * 60)
    print("F5-TTS TensorRT Engine Builder")
    print("=" * 60)
    
    gpu_info = get_gpu_info()
    print(f"Detected GPU: {gpu_info['name']}")
    print(f"Compute Capability: SM {gpu_info['compute_capability']}")
    print(f"Memory: {gpu_info['memory_gb']} GB")
    print("=" * 60 + "\n")
    
    world_size = args.cp_size * args.tp_size * args.pp_size
    assert args.pp_size == 1, "PP is not supported yet."
    
    tik = time.time()
    
    print("Step 1: Converting checkpoint...")
    execute(args.workers, [covert_and_save] * world_size, args, gpu_info)
    
    print("\nStep 2: Building engine...")
    build_engine(args, gpu_info)
    
    tok = time.time()
    t = time.strftime("%H:%M:%S", time.gmtime(tok - tik))
    print(f"\nTotal time: {t}")
    print(f"Engine saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
