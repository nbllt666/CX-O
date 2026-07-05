"""Download VoxCPM2 main model from ModelScope to c:\\CX-O\\models\\VoxCPM2.

Run:
    python c:\\CX-O\\download_voxcpm2.py
"""
import os
import sys
import time
from modelscope import snapshot_download

TARGET_DIR = r"c:\CX-O\models\VoxCPM2"
MODEL_ID = "OpenBMB/VoxCPM2"

def main():
    os.makedirs(TARGET_DIR, exist_ok=True)
    print(f"[{time.strftime('%H:%M:%S')}] start download: {MODEL_ID} -> {TARGET_DIR}", flush=True)
    local_path = snapshot_download(
        MODEL_ID,
        local_dir=TARGET_DIR,
        revision="master",
    )
    print(f"[{time.strftime('%H:%M:%S')}] done. path = {local_path}", flush=True)
    # List final artifacts
    for name in sorted(os.listdir(local_path)):
        full = os.path.join(local_path, name)
        if os.path.isfile(full):
            size_mb = os.path.getsize(full) / 1024 / 1024
            print(f"  {name:<50s} {size_mb:>10.2f} MB", flush=True)
        else:
            print(f"  {name}/", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
