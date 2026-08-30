#!/bin/bash
# Start LLM service with TensorRT-LLM
# Usage: bash start-trtllm.sh [engine_path] [port]
#
# 2026-08-30 C8：对齐 Dockerfile.trtllm 声明的 tritonserver:24.12 旧版 trtllm-serve CLI——
#   旧版需 serve 子命令，模型路径用 --model_dir，监听地址用 --host_ip（新版为
#   位置参数 + --host，勿混用）。旧版无 --max-batch-size / --max-num-tokens
#   连字符限流参数，已从命令行删除；新版 trtllm-serve 可恢复连字符限流参数
#   （届时同步更新本脚本与 Dockerfile.trtllm CMD）。

ENGINE_PATH=${1:-${ENGINE_PATH:-/workspace/engines}}
PORT=${2:-${PORT:-8080}}
HOST=${HOST:-0.0.0.0}
# 旧版 trtllm-serve 不支持限流参数，变量保留仅为向后兼容（compose/脚本调用方不破）
MAX_BATCH_SIZE=${MAX_BATCH_SIZE:-256}
MAX_NUM_TOKENS=${MAX_NUM_TOKENS:-8192}

echo "Starting TensorRT-LLM server..."
echo "  Engine: ${ENGINE_PATH}"
echo "  Host: ${HOST}:${PORT}"
echo "  Max Batch Size: ${MAX_BATCH_SIZE} (ignored by legacy trtllm-serve)"
echo "  Max Num Tokens: ${MAX_NUM_TOKENS} (ignored by legacy trtllm-serve)"

trtllm-serve serve \
    --model_dir "${ENGINE_PATH}" \
    --host_ip "${HOST}" \
    --port "${PORT}"
