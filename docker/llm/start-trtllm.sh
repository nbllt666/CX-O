#!/bin/bash
# Start LLM service with TensorRT-LLM
# Usage: bash start-trtllm.sh [engine_path] [port]

ENGINE_PATH=${1:-${ENGINE_PATH:-/workspace/engines}}
PORT=${2:-${PORT:-8080}}
HOST=${HOST:-0.0.0.0}
MAX_BATCH_SIZE=${MAX_BATCH_SIZE:-256}
MAX_NUM_TOKENS=${MAX_NUM_TOKENS:-8192}

echo "Starting TensorRT-LLM server..."
echo "  Engine: ${ENGINE_PATH}"
echo "  Host: ${HOST}:${PORT}"
echo "  Max Batch Size: ${MAX_BATCH_SIZE}"

trtllm-serve "${ENGINE_PATH}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --max-batch-size "${MAX_BATCH_SIZE}" \
    --max-num-tokens "${MAX_NUM_TOKENS}"
