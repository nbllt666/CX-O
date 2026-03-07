import argparse
import asyncio
import json
import os
import time
import numpy as np
import requests
import soundfile as sf
from typing import Optional, AsyncGenerator
import websockets


def get_args():
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--server-url", type=str, default="localhost:8000", help="Address of the server")
    parser.add_argument("--reference-audio", type=str, default="../../infer/examples/basic/basic_ref_en.wav", help="Path to reference audio file")
    parser.add_argument("--reference-text", type=str, default="Some call me nature, others call me mother nature.", help="Reference text")
    parser.add_argument("--target-text", type=str, default="I don't really care what you call me. I've been a silent spectator, watching species evolve, empires rise and fall. But always remember, I am mighty and enduring.", help="Target text to synthesize")
    parser.add_argument("--model-name", type=str, default="f5_tts", help="triton model_repo module name to request")
    parser.add_argument("--output-audio", type=str, default="tests/client_http.wav", help="Path to save the output audio")
    parser.add_argument("--stream", action="store_true", help="Enable streaming mode")
    parser.add_argument("--chunk-size", type=int, default=4096, help="Chunk size for streaming")
    return parser.parse_args()


def prepare_request(waveform, reference_text, target_text, sample_rate=24000):
    assert len(waveform.shape) == 1, "waveform should be 1D"
    lengths = np.array([[len(waveform)]], dtype=np.int32)
    waveform = waveform.reshape(1, -1).astype(np.float32)
    data = {
        "inputs": [
            {"name": "reference_wav", "shape": waveform.shape, "datatype": "FP32", "data": waveform.tolist()},
            {"name": "reference_wav_len", "shape": lengths.shape, "datatype": "INT32", "data": lengths.tolist()},
            {"name": "reference_text", "shape": [1, 1], "datatype": "BYTES", "data": [reference_text]},
            {"name": "target_text", "shape": [1, 1], "datatype": "BYTES", "data": [target_text]},
        ]
    }
    return data


def load_audio(wav_path, target_sample_rate=24000):
    assert target_sample_rate == 24000, "hard coding in server"
    if isinstance(wav_path, dict):
        waveform = wav_path["array"]
        sample_rate = wav_path["sampling_rate"]
    else:
        waveform, sample_rate = sf.read(wav_path)
    if sample_rate != target_sample_rate:
        from scipy.signal import resample
        waveform = resample(waveform, int(len(waveform) * (target_sample_rate / sample_rate)))
    return waveform, target_sample_rate


def infer_http(args):
    server_url = args.server_url
    if not server_url.startswith(("http://", "https://")):
        server_url = f"http://{server_url}"
    url = f"{server_url}/v2/models/{args.model_name}/infer"
    waveform, sr = load_audio(args.reference_audio)
    assert sr == 24000, "sample rate hardcoded in server"
    waveform = np.array(waveform, dtype=np.float32)
    data = prepare_request(waveform, args.reference_text, args.target_text)
    start_time = time.time()
    rsp = requests.post(url, headers={"Content-Type": "application/json"}, json=data, verify=False, params={"request_id": "0"})
    first_byte_time = time.time()
    result = rsp.json()
    audio = result["outputs"][0]["data"]
    audio = np.array(audio, dtype=np.float32)
    end_time = time.time()
    print(f"First byte latency: {(first_byte_time - start_time)*1000:.2f}ms")
    print(f"Total latency: {(end_time - start_time)*1000:.2f}ms")
    print(f"Audio duration: {len(audio)/24000:.2f}s")
    print(f"RTF: {(end_time - start_time)/(len(audio)/24000):.4f}")
    os.makedirs(os.path.dirname(args.output_audio), exist_ok=True)
    sf.write(args.output_audio, audio, 24000, "PCM_16")
    print(f"Audio saved to {args.output_audio}")


async def infer_stream_http(args):
    server_url = args.server_url
    if not server_url.startswith(("http://", "https://")):
        server_url = f"http://{server_url}"
    url = f"{server_url}/v2/models/{args.model_name}/stream"
    waveform, sr = load_audio(args.reference_audio)
    waveform = np.array(waveform, dtype=np.float32)
    data = prepare_request(waveform, args.reference_text, args.target_text)
    start_time = time.time()
    audio_chunks = []
    first_chunk_received = False
    async with websockets.connect(url.replace("http://", "ws://").replace("https://", "wss://")) as ws:
        await ws.send(json.dumps(data))
        while True:
            try:
                message = await ws.recv()
                if not first_chunk_received:
                    first_byte_time = time.time()
                    print(f"First chunk latency: {(first_byte_time - start_time)*1000:.2f}ms")
                    first_chunk_received = True
                chunk = json.loads(message)
                if chunk.get("done", False):
                    break
                audio_data = np.array(chunk["audio"], dtype=np.float32)
                audio_chunks.append(audio_data)
            except websockets.exceptions.ConnectionClosed:
                break
    end_time = time.time()
    audio = np.concatenate(audio_chunks)
    print(f"Total latency: {(end_time - start_time)*1000:.2f}ms")
    print(f"Audio duration: {len(audio)/24000:.2f}s")
    os.makedirs(os.path.dirname(args.output_audio), exist_ok=True)
    sf.write(args.output_audio, audio, 24000, "PCM_16")
    print(f"Audio saved to {args.output_audio}")


if __name__ == "__main__":
    args = get_args()
    if args.stream:
        asyncio.run(infer_stream_http(args))
    else:
        infer_http(args)
