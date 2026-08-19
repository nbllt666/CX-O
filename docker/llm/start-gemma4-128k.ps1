# vLLM Gemma4-E4B 128K context startup script (GPU0, port 8002)
# Purpose: rebuild vllm-gemma4 with max-model-len 8192 -> 131072 (128K context)
# Usage: powershell -ExecutionPolicy Bypass -File start-gemma4-128k.ps1
# Verified: 2026-08-18, KV cache 2.48 GiB (154,718 tokens), max_model_len 131072 OK on 20GB GPU0.
# Key params:
#   - max-model-len 131072: supports 128K context (peak 1 seq elastic)
#   - gpu-memory-utilization 0.90: enough for weights(9.46GB) + KV(2.48GB) + CUDA graph
#   - VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0: disable CUDA graph memory estimate,
#     otherwise KV cache drops to 0.33GiB and 128K init fails (ValueError)
#   - GPU0 only (--gpus "device=0"), isolated from cosyvoice/embedding on GPU1
$ErrorActionPreference = "Stop"

$CONTAINER = "vllm-gemma4"
$MODEL_VOLUME = "gemma4-models"

$existing = docker ps -a --format "{{.Names}}"
if ($existing -contains $CONTAINER) {
    Write-Host "Removing old container $CONTAINER (volume kept)"
    docker rm -f $CONTAINER
}

Write-Host "Rebuilding $CONTAINER (GPU0 / 128K context / port 8002)"
$runArgs = @(
    "run", "-d",
    "--name", $CONTAINER,
    "--gpus", "device=0",
    "-v", "${MODEL_VOLUME}:/models:ro",
    "-p", "8002:8000",
    "--shm-size=4g",
    "-e", "VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0",
    "vllm/vllm-openai:latest",
    "--model", "/models/gemma-4-e4b-it",
    "--quantization", "bitsandbytes",
    "--load-format", "auto",
    "--dtype", "bfloat16",
    "--max-model-len", "131072",
    "--gpu-memory-utilization", "0.90",
    "--tensor-parallel-size", "1",
    "--max-num-seqs", "8",
    "--host", "0.0.0.0",
    "--port", "8000",
    "--served-model-name", "gemma4-e4b",
    "--attention-backend", "triton_attn",
    "--enable-auto-tool-choice",
    "--tool-call-parser", "gemma4",
    "--reasoning-parser", "gemma4",
    # 多模态输入上限设为大值（允许图片/视频多数量输入，禁用=0 会阻断视觉能力）
    '--limit-mm-per-prompt={"image": 999, "video": 999}'
)
docker @runArgs

Write-Host "Start command issued. View logs: docker logs -f $CONTAINER"
