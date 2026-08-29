#!/bin/bash
# Start LLM service with vLLM + GGUF
# Usage: bash start-vllm.sh [model_path] [port]

MODEL_PATH=${1:-${MODEL_PATH:-/workspace/models/model.gguf}}
PORT=${2:-${PORT:-8080}}
HOST=${HOST:-0.0.0.0}
MAX_MODEL_LEN=${MAX_MODEL_LEN:-4096}
GPU_MEMORY_UTILIZATION=${GPU_MEMORY_UTILIZATION:-0.9}
DTYPE=${DTYPE:-auto}
MAX_NUM_SEQS=${MAX_NUM_SEQS:-256}

echo "Starting vLLM server..."
echo "  Model: ${MODEL_PATH}"
echo "  Host: ${HOST}:${PORT}"
echo "  Max Model Len: ${MAX_MODEL_LEN}"

# ENABLE_PREFIX_CACHING 显式比较：仅 "true" 时追加（原 ${VAR:+...} 写法在设为
# "false" 等非空值时会误开启，2026-08-29 修复；与 Dockerfile.vllm 的 ENABLE_LORA
# ="true" 判断口径一致）
PREFIX_CACHING_ARGS=""
if [ "$ENABLE_PREFIX_CACHING" = "true" ]; then
    PREFIX_CACHING_ARGS="--enable-prefix-caching"
fi

python -m vllm.entrypoints.openai.api_server \
    --model "${MODEL_PATH}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
    --dtype "${DTYPE}" \
    --max-num-seqs "${MAX_NUM_SEQS}" \
    ${PREFIX_CACHING_ARGS}
