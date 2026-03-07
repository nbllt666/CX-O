#!/usr/bin/env python3
"""
TensorRT-LLM 引擎构建脚本
使用 Python API 直接构建 F5-TTS 引擎
"""

import argparse
import json
import os
import sys
import time

import torch


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
    }


def build_engine(args, gpu_info):
    """使用 Python API 构建 TensorRT 引擎"""
    print("\n" + "=" * 60)
    print("Building TensorRT Engine")
    print("=" * 60)
    print(f"GPU: {gpu_info['name']}")
    print(f"Compute Capability: SM {gpu_info['compute_capability']}")
    print(f"Memory: {gpu_info['memory_gb']} GB")
    print("=" * 60 + "\n")
    
    sys.path.insert(0, os.path.dirname(args.model_cls_file))
    
    from tensorrt_llm.builder import Builder, BuilderConfig
    from tensorrt_llm.network import net_guard
    from tensorrt_llm import BuildConfig
    
    model_cls_dir = os.path.dirname(args.model_cls_file)
    sys.path.insert(0, model_cls_dir)
    
    import importlib.util
    spec = importlib.util.spec_from_file_location("model", args.model_cls_file)
    model_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model_module)
    F5TTS = model_module.F5TTS
    
    from tensorrt_llm.models.modeling_utils import PretrainedConfig
    
    config_path = os.path.join(args.checkpoint_dir, "config.json")
    with open(config_path, "r") as f:
        config_dict = json.load(f)
    
    config = PretrainedConfig.from_dict(config_dict)
    
    print("Loading model...")
    model = F5TTS(config)
    
    print("Loading weights...")
    import safetensors.torch
    weights_path = os.path.join(args.checkpoint_dir, "rank0.safetensors")
    weights = safetensors.torch.load_file(weights_path)
    model.load_weights(weights)
    
    print("Creating builder...")
    builder = Builder()
    
    build_config = BuildConfig(
        max_batch_size=args.max_batch_size,
        max_input_len=args.max_input_len,
        max_seq_len=args.max_seq_len,
        max_num_tokens=args.max_seq_len * args.max_batch_size,
    )
    
    builder_config = BuilderConfig(
        name="F5TTS",
        precision="float16",
        tensor_parallel=1,
        gpus_per_node=1,
    )
    
    print("Building engine...")
    tik = time.time()
    
    engine = builder.build_engine(model, builder_config)
    
    tok = time.time()
    print(f"Engine built in {time.strftime('%H:%M:%S', time.gmtime(tok - tik))}")
    
    os.makedirs(args.output_dir, exist_ok=True)
    engine.save(args.output_dir)
    print(f"Engine saved to {args.output_dir}")
    
    config_output = {
        "version": "0.16.0",
        "pretrained_config": config_dict,
        "build_config": {
            "max_input_len": args.max_input_len,
            "max_seq_len": args.max_seq_len,
            "max_batch_size": args.max_batch_size,
            "opt_batch_size": 2,
        }
    }
    
    with open(os.path.join(args.output_dir, "config.json"), "w") as f:
        json.dump(config_output, f, indent=4)
    
    return True


def main():
    parser = argparse.ArgumentParser(description="Build TensorRT engine for F5-TTS")
    parser.add_argument("--model_path", type=str, default="/models/F5TTS_Base/model_1200000.pt")
    parser.add_argument("--checkpoint_dir", type=str, default="/tmp/trtllm_checkpoint")
    parser.add_argument("--output_dir", type=str, default="/engines_new")
    parser.add_argument("--model_cls_file", type=str, default="/tmp/scripts/f5tts/model.py")
    parser.add_argument("--max_batch_size", type=int, default=8)
    parser.add_argument("--max_input_len", type=int, default=1024)
    parser.add_argument("--max_seq_len", type=int, default=2048)
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("F5-TTS TensorRT Engine Builder")
    print("=" * 60)
    
    gpu_info = get_gpu_info()
    print(f"Detected GPU: {gpu_info['name']}")
    print(f"Compute Capability: SM {gpu_info['compute_capability']}")
    print(f"Memory: {gpu_info['memory_gb']} GB")
    print("=" * 60 + "\n")
    
    tik = time.time()
    build_engine(args, gpu_info)
    tok = time.time()
    
    print("\n" + "=" * 60)
    print(f"Total time: {time.strftime('%H:%M:%S', time.gmtime(tok - tik))}")
    print(f"Engine saved to: {args.output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
