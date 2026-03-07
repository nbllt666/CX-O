#!/usr/bin/env python3
import argparse
import base64
import json
import wave
import numpy as np
import requests
import time


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", type=str, default="http://localhost:8000")
    parser.add_argument(
        "--reference-audio",
        type=str,
        required=False,
        default=None,
    )
    parser.add_argument("--reference-text", type=str, required=False, default=None)
    parser.add_argument("--target-text", type=str, required=False, default=None)
    parser.add_argument("--model-name", type=str, default="f5_tts")
    return parser.parse_args()


def encode_wav(wav_path):
    with wave.open(wav_path, "rb") as f:
        pcm_data = f.readframes(f.getnframes())
        sample_rate = f.getframerate()
        n_channels = f.getnchannels()
        n_frames = f.getnframes()
    wav_bytes = base64.b64encode(pcm_data).decode("utf-8")
    return {
        "wav": wav_bytes,
        "sample_rate": sample_rate,
        "n_channels": n_channels,
        "n_frames": n_frames,
    }


def main():
    args = parse_args()

    reference_audio_info = encode_wav(args.reference_audio)

    # Prepare the input data
    data = {
        "inputs": [
            {
                "name": "reference_wav",
                "shape": [1, reference_audio_info["n_frames"]],
                "datatype": "FP32",
                "data": np.frombuffer(
                    base64.b64decode(reference_audio_info["wav"]),
                    dtype=np.float32,
                )
                .reshape([1, -1])
                .tolist(),
            },
            {
                "name": "reference_wav_len",
                "shape": [1, 1],
                "datatype": "INT32",
                "data": [reference_audio_info["n_frames"]],
            },
            {
                "name": "reference_text",
                "shape": [1, 1],
                "datatype": "BYTES",
                "data": [[args.reference_text]],
            },
            {
                "name": "target_text",
                "shape": [1, 1],
                "datatype": "BYTES",
                "data": [[args.target_text]],
            },
        ]
    }

    url = f"{args.url}/v2/models/{args.model_name}/infer"

    start = time.time()
    response = requests.post(url, json=data, timeout=120)
    elapsed = time.time() - start

    if response.status_code == 200:
        print(f"Success! Time: {elapsed:.2f}s")
        result = response.json()
        print(f"Response: {json.dumps(result, indent=2)[:500]}")
    else:
        print(f"Error: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    main()
