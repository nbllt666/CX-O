#!/usr/bin/env python3
import os
import json
import time

print("Starting TensorRT-LLM engine build...")

checkpoint_dir = "/tmp/f5tts/ckpts/F5TTS_v1_Base/trtllm_ckpt"
output_dir = "/tmp/f5tts/ckpts/F5TTS_v1_Base/trtllm_engine"

print(f"Checkpoint dir: {checkpoint_dir}")
print(f"Output dir: {output_dir}")

os.makedirs(output_dir, exist_ok=True)

print("Loading config...")
with open(os.path.join(checkpoint_dir, "config.json")) as f:
    config = json.load(f)
print(f"Config: {json.dumps(config, indent=2)}")

print("Importing TensorRT-LLM...")
from tensorrt_llm.commands.build import build

print("Building engine...")
start = time.time()

build(
    checkpoint_dir=checkpoint_dir,
    output_dir=output_dir,
    max_batch_size=8,
    remove_input_padding=False,
)

print(f"Engine built in {time.time()-start:.2f}s")
print("Output files:", os.listdir(output_dir))
