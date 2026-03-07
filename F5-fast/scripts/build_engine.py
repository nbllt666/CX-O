#!/usr/bin/env python3
"""
TensorRT-LLM 引擎构建脚本
使用 trtllm-build 为当前 GPU 构建 F5-TTS 引擎
"""

import argparse
import json
import os
import subprocess
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


def convert_checkpoint(args):
    """转换 PyTorch checkpoint 为 TensorRT-LLM 格式"""
    print("\n" + "=" * 60)
    print("Step 1: Converting Checkpoint")
    print("=" * 60)
    
    cmd = [
        "python3", "/tmp/scripts/convert_checkpoint.py",
        "--model_name", "F5TTS_Base",
        "--timm_ckpt", args.model_path,
        "--output_dir", args.checkpoint_dir,
        "--hidden_size", "1024",
        "--depth", "22",
        "--num_heads", "16",
        "--dtype", args.dtype,
        "--tp_size", "1",
        "--workers", "1",
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    tik = time.time()
    result = subprocess.run(cmd, capture_output=False)
    tok = time.time()
    
    if result.returncode != 0:
        raise RuntimeError(f"Checkpoint conversion failed with code {result.returncode}")
    
    print(f"Checkpoint converted in {time.strftime('%H:%M:%S', time.gmtime(tok - tik))}")
    return True


def build_engine(args, gpu_info):
    """使用 trtllm-build 构建 TensorRT 引擎"""
    print("\n" + "=" * 60)
    print("Step 2: Building TensorRT Engine")
    print("=" * 60)
    print(f"GPU: {gpu_info['name']}")
    print(f"Compute Capability: SM {gpu_info['compute_capability']}")
    print(f"Memory: {gpu_info['memory_gb']} GB")
    print("=" * 60 + "\n")
    
    cmd = [
        "trtllm-build",
        "--checkpoint_dir", args.checkpoint_dir,
        "--output_dir", args.output_dir,
        "--model_cls_file", "/tmp/scripts/f5tts/model.py",
        "--model_cls_name", "F5TTS",
        "--max_batch_size", str(args.max_batch_size),
        "--max_input_len", str(args.max_input_len),
        "--max_seq_len", str(args.max_seq_len),
        "--gpus_per_node", "1",
        "--gemm_plugin", "auto",
        "--bert_attention_plugin", "auto",
        "--gpt_attention_plugin", "auto",
        "--remove_input_padding", "enable",
        "--log_level", "info",
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    tik = time.time()
    result = subprocess.run(cmd, capture_output=False)
    tok = time.time()
    
    if result.returncode != 0:
        raise RuntimeError(f"Engine build failed with code {result.returncode}")
    
    print(f"Engine built in {time.strftime('%H:%M:%S', time.gmtime(tok - tik))}")
    return True


def verify_engine(args):
    """验证引擎是否正确生成"""
    print("\n" + "=" * 60)
    print("Step 3: Verifying Engine")
    print("=" * 60)
    
    engine_file = os.path.join(args.output_dir, "rank0.engine")
    config_file = os.path.join(args.output_dir, "config.json")
    
    if not os.path.exists(engine_file):
        raise RuntimeError(f"Engine file not found: {engine_file}")
    
    if not os.path.exists(config_file):
        raise RuntimeError(f"Config file not found: {config_file}")
    
    engine_size_mb = os.path.getsize(engine_file) / (1024 * 1024)
    print(f"Engine file: {engine_file}")
    print(f"Engine size: {engine_size_mb:.1f} MB")
    
    with open(config_file, "r") as f:
        config = json.load(f)
    
    print(f"Config version: {config.get('version', 'N/A')}")
    print(f"Architecture: {config['pretrained_config'].get('architecture', 'N/A')}")
    
    if "build_config" in config:
        build_config = config["build_config"]
        if "auto_parallel_config" in build_config:
            cluster_key = build_config["auto_parallel_config"].get("cluster_key", "N/A")
            print(f"Cluster key: {cluster_key}")
    
    print("\nEngine verification successful!")
    return True


def main():
    parser = argparse.ArgumentParser(description="Build TensorRT engine for F5-TTS")
    parser.add_argument("--model_path", type=str, default="/models/F5TTS_Base/model_1200000.pt")
    parser.add_argument("--checkpoint_dir", type=str, default="/tmp/trtllm_checkpoint")
    parser.add_argument("--output_dir", type=str, default="/engines_new")
    parser.add_argument("--dtype", type=str, default="float16", choices=["float16", "float32", "bfloat16"])
    parser.add_argument("--max_batch_size", type=int, default=8)
    parser.add_argument("--max_input_len", type=int, default=1024)
    parser.add_argument("--max_seq_len", type=int, default=2048)
    parser.add_argument("--skip_convert", action="store_true", help="Skip checkpoint conversion")
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
    
    if not args.skip_convert:
        convert_checkpoint(args)
    else:
        print("Skipping checkpoint conversion...")
    
    build_engine(args, gpu_info)
    verify_engine(args)
    
    tok = time.time()
    print("\n" + "=" * 60)
    print(f"Total time: {time.strftime('%H:%M:%S', time.gmtime(tok - tik))}")
    print(f"Engine saved to: {args.output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
