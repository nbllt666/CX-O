#!/usr/bin/env python3
import os
import json
import time

print("Step 1: Importing modules...")
import torch
from safetensors.torch import load_file as load_safetensors

print("Step 2: Loading model...")
start = time.time()
model_params = load_safetensors('/tmp/f5tts/ckpts/F5TTS_v1_Base/model_1250000.safetensors')
print(f"Loaded in {time.time()-start:.2f}s, {len(model_params)} keys")

print("Step 3: Converting to float16...")
torch_dtype = torch.float16
weights = {}
for name, param in model_params.items():
    weights[name] = param.contiguous().to(torch_dtype)
print(f"Converted {len(weights)} weights")

print("Step 4: Creating output directory...")
output_dir = '/tmp/f5tts/ckpts/F5TTS_v1_Base/trtllm_ckpt'
os.makedirs(output_dir, exist_ok=True)

print("Step 5: Saving config...")
config = {
    "architecture": "F5TTS",
    "dtype": "float16",
    "hidden_size": 1024,
    "num_hidden_layers": 22,
    "num_attention_heads": 16,
    "dim_head": 64,
    "dropout": 0.0,
    "ff_mult": 2,
    "mel_dim": 100,
    "text_dim": 512,
    "text_mask_padding": True,
    "conv_layers": 4,
    "pe_attn_head": None,
    "mapping": {"world_size": 1, "cp_size": 1, "tp_size": 1, "pp_size": 1},
}
with open(os.path.join(output_dir, "config.json"), "w") as f:
    json.dump(config, f, indent=4)
print("Config saved")

print("Step 6: Saving weights...")
import safetensors.torch
safetensors.torch.save_file(weights, os.path.join(output_dir, "rank0.safetensors"))
print("Weights saved!")

print("Done! Output:", output_dir)
print("Files:", os.listdir(output_dir))
