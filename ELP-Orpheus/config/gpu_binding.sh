#!/usr/bin/env bash
# ============================================================================
# ELP-Orpheus 双卡物理隔离 GPU 绑定启动脚本
# ============================================================================
# 部署目标：Linux 双卡服务器（2 × RTX 3080 20GB）
#
# 双卡物理隔离的目的（核心设计决策）：
#   1. GPU 0 专属 Gemma 4 E4B（FT 引擎）—— 保住 LLM 首 token 延迟（TTFT）<80ms
#   2. GPU 1 专属 Orpheus TTS（FT 骨干 + Audio Head + SNAC 解码器）
#   3. 两张卡各自独立显存与显存带宽，互不争抢：
#      - 避免 Orpheus SNAC 解码产生的大显存带宽峰值拖慢 Gemma 解码
#      - 避免 KV Cache 与 Audio Head 中间张量互相挤占导致 OOM 或 GC 抖动
#      - 使两条推理流水线的延迟曲线互相解耦，各自可独立 p99 优化
#
# 通过 CUDA_VISIBLE_DEVICES 环境变量实现进程级 GPU 绑定：
#   - Gemma 进程只看得见 GPU 0（物理 device 0）
#   - Orpheus 进程只看得见 GPU 1（物理 device 1）
#   这样即使两个进程同机运行，CUDA runtime 也会把它们分别路由到不同物理卡。
#
# 用法:
#   ./gpu_binding.sh start    # 启动双卡进程（先 Gemma GPU0，再 Orpheus GPU1）
#   ./gpu_binding.sh stop     # 停止双卡进程
#   ./gpu_binding.sh status   # 查看双卡进程运行状态
# ============================================================================

set -euo pipefail

# ----------------------------------------------------------------------------
# 全局配置（与 config/engine.yaml 保持一致）
# ----------------------------------------------------------------------------
# 项目根目录（脚本所在目录的上一级）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 进程 PID 文件存放目录
PID_DIR="${PROJECT_ROOT}/.run"
mkdir -p "${PID_DIR}"

# Gemma 4 E4B 进程
GEMMA_PID_FILE="${PID_DIR}/gemma.pid"
GEMMA_LOG_FILE="${PID_DIR}/gemma.log"

# Orpheus TTS 进程
ORPHEUS_PID_FILE="${PID_DIR}/orpheus.pid"
ORPHEUS_LOG_FILE="${PID_DIR}/orpheus.log"

# Python 解释器（按实际环境调整，建议使用 conda/venv 环境）
PYTHON_BIN="${PYTHON_BIN:-python3}"

# ============================================================================
# 启动 Gemma 4 E4B FT 进程（绑定 GPU 0）
# ============================================================================
# 通过 CUDA_VISIBLE_DEVICES=0 把该进程的可见 GPU 限制为物理 GPU 0，
# 进程内部 device_id 视为 0，实际落在物理 3080 #0 上。
start_gemma() {
    echo "[Gemma] 启动 Gemma 4 E4B FT 引擎（绑定 GPU 0）..."

    # 检查是否已在运行
    if [[ -f "${GEMMA_PID_FILE}" ]] && kill -0 "$(cat "${GEMMA_PID_FILE}")" 2>/dev/null; then
        echo "[Gemma] 已在运行（PID=$(cat "${GEMMA_PID_FILE}")），跳过启动。"
        return 0
    fi

    # CUDA_VISIBLE_DEVICES=0：物理隔离，Gemma 进程只能看到 GPU 0
    # 必须先于 Gemma 启动，保证 LLM TTFT 不被 Orpheus 解码带宽抢占
    CUDA_VISIBLE_DEVICES=0 \
        "${PYTHON_BIN}" -m ft_engine.gemma_server \
        > "${GEMMA_LOG_FILE}" 2>&1 &

    local pid=$!
    echo "${pid}" > "${GEMMA_PID_FILE}"
    echo "[Gemma] 已启动，PID=${pid}，日志=${GEMMA_LOG_FILE}"
}

# ============================================================================
# 启动 Orpheus TTS FT 进程（绑定 GPU 1）
# ============================================================================
# 通过 CUDA_VISIBLE_DEVICES=1 把该进程的可见 GPU 限制为物理 GPU 1，
# 进程内部 device_id 视为 0，实际落在物理 3080 #1 上。
# 注意：由于 CUDA_VISIBLE_DEVICES 过滤，进程内 device_id 永远从 0 开始编号，
#       因此 Orpheus 进程内 ft.gpu1.device_id 应映射为本地 0（脚本已隔离）。
start_orpheus() {
    echo "[Orpheus] 启动 Orpheus TTS FT 引擎（绑定 GPU 1）..."

    # 检查是否已在运行
    if [[ -f "${ORPHEUS_PID_FILE}" ]] && kill -0 "$(cat "${ORPHEUS_PID_FILE}")" 2>/dev/null; then
        echo "[Orpheus] 已在运行（PID=$(cat "${ORPHEUS_PID_FILE}")），跳过启动。"
        return 0
    fi

    # CUDA_VISIBLE_DEVICES=1：物理隔离，Orpheus 进程只能看到 GPU 1
    CUDA_VISIBLE_DEVICES=1 \
        "${PYTHON_BIN}" -m ft_engine.orpheus_server \
        > "${ORPHEUS_LOG_FILE}" 2>&1 &

    local pid=$!
    echo "${pid}" > "${ORPHEUS_PID_FILE}"
    echo "[Orpheus] 已启动，PID=${pid}，日志=${ORPHEUS_LOG_FILE}"
}

# ============================================================================
# 停止进程的通用函数
# ============================================================================
stop_proc() {
    local name="$1"
    local pid_file="$2"

    if [[ ! -f "${pid_file}" ]]; then
        echo "[${name}] 未发现 PID 文件，进程可能未运行。"
        return 0
    fi

    local pid
    pid="$(cat "${pid_file}")"

    if kill -0 "${pid}" 2>/dev/null; then
        echo "[${name}] 正在停止进程 PID=${pid} ..."
        kill "${pid}" 2>/dev/null || true
        # 优雅等待退出，最多 10 秒
        for _ in $(seq 1 10); do
            kill -0 "${pid}" 2>/dev/null || break
            sleep 1
        done
        # 仍未退出则强杀
        if kill -0 "${pid}" 2>/dev/null; then
            echo "[${name}] 进程未响应，强制终止 PID=${pid} ..."
            kill -9 "${pid}" 2>/dev/null || true
        fi
        echo "[${name}] 已停止。"
    else
        echo "[${name}] 进程未运行（PID=${pid} 已退出）。"
    fi

    rm -f "${pid_file}"
}

# ============================================================================
# 查看进程状态
# ============================================================================
status_proc() {
    local name="$1"
    local pid_file="$2"

    if [[ -f "${pid_file}" ]] && kill -0 "$(cat "${pid_file}")" 2>/dev/null; then
        echo "[${name}] 运行中，PID=$(cat "${pid_file}")"
    else
        echo "[${name}] 未运行"
    fi
}

# ============================================================================
# 主入口：start / stop / status
# ============================================================================
case "${1:-}" in
    start)
        # 启动顺序：先 Gemma GPU0，再 Orpheus GPU1
        # Gemma 是 Token 生产者，必须先就绪，Orpheus 才能消费 Token ID 流
        start_gemma
        # 等待 Gemma 初始化（加载 FT checkpoint、预热 CUDA Graphs）
        echo "[Main] 等待 Gemma 初始化完成（2s）..."
        sleep 2
        start_orpheus
        echo "[Main] 双卡进程启动完成。"
        ;;
    stop)
        # 停止顺序：先停 Orpheus（消费者），再停 Gemma（生产者），避免悬空 Token 流
        stop_proc "Orpheus" "${ORPHEUS_PID_FILE}"
        stop_proc "Gemma"   "${GEMMA_PID_FILE}"
        echo "[Main] 双卡进程已停止。"
        ;;
    status)
        status_proc "Gemma"   "${GEMMA_PID_FILE}"
        status_proc "Orpheus" "${ORPHEUS_PID_FILE}"
        ;;
    *)
        echo "用法: $0 {start|stop|status}"
        echo "  start  — 启动双卡进程（先 Gemma GPU0，再 Orpheus GPU1）"
        echo "  stop   — 停止双卡进程（先 Orpheus，再 Gemma）"
        echo "  status — 查看双卡进程运行状态"
        exit 1
        ;;
esac
