"""Download VoxCPM support models: ZipEnhancer + SenseVoiceSmall.

Models:
  - iic/speech_zipenhancer_ans_multiloss_16k_base (denoiser, ~200MB)
  - iic/SenseVoiceSmall (ASR for WebUI auto-transcribe, ~400MB)

Run:
    python c:\\CX-O\\download_voxcpm_support.py
"""
import os
import sys
import time
from modelscope import snapshot_download

TARGET_BASE = r"c:\CX-O\models"

MODELS = [
    ("iic/speech_zipenhancer_ans_multiloss_16k_base", "zipenhancer_16k"),
    ("iic/SenseVoiceSmall", "SenseVoiceSmall"),
]

def download_one(model_id, local_name):
    target_dir = os.path.join(TARGET_BASE, local_name)
    os.makedirs(target_dir, exist_ok=True)
    print(f"[{time.strftime('%H:%M:%S')}] start: {model_id} -> {target_dir}", flush=True)
    local_path = snapshot_download(
        model_id,
        local_dir=target_dir,
        revision="master",
    )
    print(f"[{time.strftime('%H:%M:%S')}] done: {local_path}", flush=True)
    # List artifacts
    for name in sorted(os.listdir(local_path)):
        full = os.path.join(local_path, name)
        if os.path.isfile(full):
            size_mb = os.path.getsize(full) / 1024 / 1024
            print(f"  {name:<50s} {size_mb:>10.2f} MB", flush=True)
        else:
            print(f"  {name}/", flush=True)

def main():
    for model_id, local_name in MODELS:
        try:
            download_one(model_id, local_name)
        except Exception as e:
            print(f"[ERROR] {model_id}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            # continue to next model

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)