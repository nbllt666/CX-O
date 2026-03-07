#!/usr/bin/env python3
"""
F5-TTS Triton gRPC Client

A command-line client for F5-TTS inference via Triton Inference Server.
Supports single inference and benchmarking with concurrent tasks.
"""

import argparse
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import tritonclient.grpc as grpcclient
from tritonclient.utils import np_to_triton_dtype

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_NAME = "f5_tts"
SAMPLE_RATE = 24000


@dataclass
class InferenceResult:
    audio: np.ndarray
    latency_ms: float
    sample_rate: int = SAMPLE_RATE


@dataclass
class LatencyStats:
    mean_ms: float
    std_ms: float
    min_ms: float
    max_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    total_requests: int
    throughput_rps: float


def load_audio(audio_path: str, target_sample_rate: int = SAMPLE_RATE) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(audio_path, dtype="float32")
    if len(audio.shape) > 1:
        audio = audio[:, 0]
    if sr != target_sample_rate:
        import librosa
        audio = librosa.resample(audio, orig_sr=sr, target_sr=target_sample_rate)
        sr = target_sample_rate
    return audio, sr


def infer_grpc(
    triton_url: str,
    reference_audio: np.ndarray,
    reference_text: str,
    target_text: str,
    speed: float = 1.0,
) -> InferenceResult:
    wav_len = np.array([len(reference_audio)], dtype=np.int32)
    reference_wav = reference_audio.astype(np.float32).reshape(1, -1)

    inputs = [
        grpcclient.InferInput("reference_wav", reference_wav.shape, np_to_triton_dtype(np.float32)),
        grpcclient.InferInput("reference_wav_len", wav_len.shape, np_to_triton_dtype(np.int32)),
        grpcclient.InferInput("reference_text", [1, 1], "BYTES"),
        grpcclient.InferInput("target_text", [1, 1], "BYTES"),
    ]

    inputs[0].set_data_from_numpy(reference_wav)
    inputs[1].set_data_from_numpy(wav_len)
    inputs[2].set_data_from_numpy(np.array([[reference_text.encode("utf-8")]], dtype=np.object_))
    inputs[3].set_data_from_numpy(np.array([[target_text.encode("utf-8")]], dtype=np.object_))

    outputs = [grpcclient.InferRequestedOutput("waveform")]

    client = grpcclient.InferenceServerClient(url=triton_url, verbose=False)

    start_time = time.perf_counter()
    try:
        response = client.infer(
            model_name=MODEL_NAME,
            inputs=inputs,
            outputs=outputs,
        )
        end_time = time.perf_counter()
        latency_ms = (end_time - start_time) * 1000

        waveform = response.as_numpy("waveform")
        audio = waveform.flatten()

        if speed != 1.0:
            import librosa
            audio = librosa.effects.time_stretch(audio, rate=speed)

        return InferenceResult(audio=audio, latency_ms=latency_ms)

    except Exception as e:
        logger.error(f"Inference failed: {e}")
        raise


def infer_grpc_batch(
    triton_url: str,
    batch_requests: list[tuple[np.ndarray, str, str]],
) -> list[InferenceResult]:
    results = []

    for reference_audio, reference_text, target_text in batch_requests:
        result = infer_grpc(
            triton_url=triton_url,
            reference_audio=reference_audio,
            reference_text=reference_text,
            target_text=target_text,
        )
        results.append(result)

    return results


def _run_single_benchmark(
    triton_url: str,
    reference_audio: np.ndarray,
    reference_text: str,
    target_text: str,
    iteration: int,
) -> float:
    result = infer_grpc(
        triton_url=triton_url,
        reference_audio=reference_audio,
        reference_text=reference_text,
        target_text=target_text,
    )
    logger.debug(f"Iteration {iteration}: {result.latency_ms:.2f}ms")
    return result.latency_ms


def benchmark_inference(
    triton_url: str,
    reference_audio: np.ndarray,
    reference_text: str,
    target_text: str,
    num_tasks: int = 1,
    num_iterations: int = 10,
    warmup: int = 3,
) -> LatencyStats:
    logger.info(f"Starting benchmark with {warmup} warmup iterations...")

    for i in range(warmup):
        _ = infer_grpc(
            triton_url=triton_url,
            reference_audio=reference_audio,
            reference_text=reference_text,
            target_text=target_text,
        )
        logger.info(f"Warmup {i + 1}/{warmup} completed")

    logger.info(f"Running benchmark: {num_iterations} iterations with {num_tasks} concurrent tasks...")

    latencies = []

    if num_tasks == 1:
        start_time = time.perf_counter()
        for i in range(num_iterations):
            latency = _run_single_benchmark(
                triton_url=triton_url,
                reference_audio=reference_audio,
                reference_text=reference_text,
                target_text=target_text,
                iteration=i + 1,
            )
            latencies.append(latency)
        total_time = time.perf_counter() - start_time
    else:
        start_time = time.perf_counter()
        with ThreadPoolExecutor(max_workers=num_tasks) as executor:
            futures = []
            for i in range(num_iterations):
                future = executor.submit(
                    _run_single_benchmark,
                    triton_url,
                    reference_audio,
                    reference_text,
                    target_text,
                    i + 1,
                )
                futures.append(future)

            for future in futures:
                latencies.append(future.result())
        total_time = time.perf_counter() - start_time

    latencies = np.array(latencies)

    stats = LatencyStats(
        mean_ms=np.mean(latencies),
        std_ms=np.std(latencies),
        min_ms=np.min(latencies),
        max_ms=np.max(latencies),
        p50_ms=np.percentile(latencies, 50),
        p95_ms=np.percentile(latencies, 95),
        p99_ms=np.percentile(latencies, 99),
        total_requests=num_iterations,
        throughput_rps=num_iterations / total_time,
    )

    return stats


def save_audio(audio: np.ndarray, output_path: str, sample_rate: int = SAMPLE_RATE) -> None:
    output_dir = Path(output_path).parent
    if output_dir and not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    sf.write(output_path, audio, sample_rate)
    logger.info(f"Audio saved to: {output_path}")


def print_latency_stats(stats: LatencyStats) -> None:
    print("\n" + "=" * 50)
    print("Benchmark Results")
    print("=" * 50)
    print(f"Total Requests:     {stats.total_requests}")
    print(f"Throughput:         {stats.throughput_rps:.2f} req/s")
    print("-" * 50)
    print("Latency Statistics (ms):")
    print(f"  Mean:             {stats.mean_ms:.2f}")
    print(f"  Std:              {stats.std_ms:.2f}")
    print(f"  Min:              {stats.min_ms:.2f}")
    print(f"  Max:              {stats.max_ms:.2f}")
    print(f"  P50:              {stats.p50_ms:.2f}")
    print(f"  P95:              {stats.p95_ms:.2f}")
    print(f"  P99:              {stats.p99_ms:.2f}")
    print("=" * 50 + "\n")


def check_server_ready(triton_url: str) -> bool:
    try:
        client = grpcclient.InferenceServerClient(url=triton_url, verbose=False)
        ready = client.is_server_ready()
        if ready:
            logger.info(f"Triton server at {triton_url} is ready")
        else:
            logger.error(f"Triton server at {triton_url} is not ready")
        return ready
    except Exception as e:
        logger.error(f"Failed to connect to Triton server: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="F5-TTS Triton gRPC Client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single inference
  python client_grpc.py --reference-audio ref.wav --reference-text "Hello" --target-text "World" --output out.wav

  # Benchmark with 4 concurrent tasks
  python client_grpc.py --reference-audio ref.wav --reference-text "Hello" --target-text "World" --num-tasks 4 --num-iterations 100
        """,
    )

    parser.add_argument(
        "--reference-audio",
        type=str,
        required=True,
        help="Path to reference audio file",
    )
    parser.add_argument(
        "--reference-text",
        type=str,
        required=True,
        help="Reference text (transcription of reference audio)",
    )
    parser.add_argument(
        "--target-text",
        type=str,
        required=True,
        help="Text to synthesize",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output.wav",
        help="Output audio file path (default: output.wav)",
    )
    parser.add_argument(
        "--triton-url",
        type=str,
        default="localhost:8001",
        help="Triton server gRPC URL (default: localhost:8001)",
    )
    parser.add_argument(
        "--num-tasks",
        type=int,
        default=1,
        help="Number of concurrent tasks for benchmarking (default: 1)",
    )
    parser.add_argument(
        "--num-iterations",
        type=int,
        default=10,
        help="Number of benchmark iterations (default: 10)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=3,
        help="Number of warmup iterations (default: 3)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed multiplier (default: 1.0)",
    )
    parser.add_argument(
        "--benchmark-only",
        action="store_true",
        help="Run benchmark only, do not save output audio",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not check_server_ready(args.triton_url):
        logger.error("Triton server is not ready. Exiting.")
        return 1

    if not Path(args.reference_audio).exists():
        logger.error(f"Reference audio file not found: {args.reference_audio}")
        return 1

    logger.info(f"Loading reference audio: {args.reference_audio}")
    reference_audio, sr = load_audio(args.reference_audio)
    logger.info(f"Audio loaded: {len(reference_audio)} samples at {sr}Hz")

    if args.benchmark_only or args.num_iterations > 1 or args.num_tasks > 1:
        stats = benchmark_inference(
            triton_url=args.triton_url,
            reference_audio=reference_audio,
            reference_text=args.reference_text,
            target_text=args.target_text,
            num_tasks=args.num_tasks,
            num_iterations=args.num_iterations,
            warmup=args.warmup,
        )
        print_latency_stats(stats)

        if not args.benchmark_only:
            logger.info("Running final inference for output...")
            result = infer_grpc(
                triton_url=args.triton_url,
                reference_audio=reference_audio,
                reference_text=args.reference_text,
                target_text=args.target_text,
                speed=args.speed,
            )
            save_audio(result.audio, args.output, result.sample_rate)
            logger.info(f"Final inference latency: {result.latency_ms:.2f}ms")
    else:
        result = infer_grpc(
            triton_url=args.triton_url,
            reference_audio=reference_audio,
            reference_text=args.reference_text,
            target_text=args.target_text,
            speed=args.speed,
        )
        logger.info(f"Inference completed in {result.latency_ms:.2f}ms")
        save_audio(result.audio, args.output, result.sample_rate)

    return 0


if __name__ == "__main__":
    exit(main())
