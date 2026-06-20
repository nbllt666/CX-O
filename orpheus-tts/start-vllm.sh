#!/bin/bash
# ============================================================
# Orpheus TTS vLLM 后端启动脚本
# 加载 canopylabs/orpheus-multilingual-research-release 模型
# 启用 FlashInfer 注意力后端，监听 8000 端口（容器内部）
# ============================================================
# 用法:
#   bash start-vllm.sh
#
# 环境变量（可通过 .env 覆盖）:
#   ORPHEUS_MODEL              模型名称/路径
#   VLLM_ATTENTION_BACKEND     注意力后端（FLASHINFER）
#   CUDA_VISIBLE_DEVICES       GPU 设备 ID
#   ORPHEUS_MAX_MODEL_LEN      最大上下文长度
#   ORPHEUS_GPU_MEM_UTIL       GPU 显存利用率
#   ORPHEUS_DTYPE              数据类型（auto/bfloat16/float16）
#   ORPHEUS_MAX_NUM_SEQS       最大并发序列数
# ============================================================

set -euo pipefail

# ---- 模型配置 ----
MODEL="${ORPHEUS_MODEL:-canopylabs/orpheus-multilingual-research-release}"
HOST="${VLLM_HOST:-0.0.0.0}"
PORT="${VLLM_PORT:-8000}"

# ---- vLLM 推理参数 ----
MAX_MODEL_LEN="${ORPHEUS_MAX_MODEL_LEN:-4096}"
GPU_MEM_UTIL="${ORPHEUS_GPU_MEM_UTIL:-0.9}"
DTYPE="${ORPHEUS_DTYPE:-auto}"
MAX_NUM_SEQS="${ORPHEUS_MAX_NUM_SEQS:-8}"

# ---- 注意力后端（FlashInfer）----
export VLLM_ATTENTION_BACKEND="${VLLM_ATTENTION_BACKEND:-FLASHINFER}"

echo "============================================================"
echo "  Orpheus TTS vLLM 后端启动"
echo "============================================================"
echo "  模型:           ${MODEL}"
echo "  监听:           ${HOST}:${PORT}"
echo "  注意力后端:     ${VLLM_ATTENTION_BACKEND}"
echo "  CUDA_VISIBLE:   ${CUDA_VISIBLE_DEVICES:-未指定（使用全部可见 GPU）}"
echo "  最大上下文:     ${MAX_MODEL_LEN}"
echo "  显存利用率:     ${GPU_MEM_UTIL}"
echo "  数据类型:       ${DTYPE}"
echo "  最大并发:       ${MAX_NUM_SEQS}"
echo "============================================================"

# 启动 vLLM OpenAI 兼容服务
# --trust-remote-code: Orpheus 模型需要远程代码执行权限
# --enable-prefix-caching: 缓存 voice 前缀，降低重复请求延迟
exec python -m vllm.entrypoints.openai.api_server \
    --model "${MODEL}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --max-model-len "${MAX_MODEL_LEN}" \
    --gpu-memory-utilization "${GPU_MEM_UTIL}" \
    --dtype "${DTYPE}" \
    --max-num-seqs "${MAX_NUM_SEQS}" \
    --trust-remote-code \
    --enable-prefix-caching
