# Qwen3-TTS vLLM-Omni 部署脚本（Task 0 交付物：GPU1 启动 / 端口 8091 / VoiceDesign 模型）
# 用法: powershell -ExecutionPolicy Bypass -File start-qwen3-tts.ps1
# 前提: vllm/vllm-omni:latest 已拉取; C:\CX-O\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign 已下载
$ErrorActionPreference = "Stop"

$IMAGE = "vllm/vllm-omni:latest"
$CONTAINER = "qwen3-tts-vllm"
$PORT = "8091"
$MODEL_HOST = "C:\CX-O\models"
$MODEL_NAME = "Qwen3-TTS-12Hz-1.7B-VoiceDesign"
$MODEL_CONTAINER = "/models/$MODEL_NAME"

# 已存在则先停旧容器（保留日志重建）
$existing = docker ps -a --format "{{.Names}}"
if ($existing -contains $CONTAINER) {
    Write-Host "清理旧容器 $CONTAINER"
    docker rm -f $CONTAINER
}

Write-Host "启动 $CONTAINER (GPU1 / port $PORT / $MODEL_NAME)"
# 注意: --gpus all + CUDA_VISIBLE_DEVICES=1 显式锁定空闲 GPU。
# 实证: Docker --gpus device=ID 与容器内 CUDA 索引不一致(见 gemma4 声明 device=1 却跑在 CUDA0)，
#       故用 CUDA_VISIBLE_DEVICES=1 由 vLLM 直接选择空闲 GPU。
$runArgs = @(
    "run", "-d",
    "--name", $CONTAINER,
    "--gpus", "all",
    "-e", "CUDA_VISIBLE_DEVICES=1",
    "-v", "${MODEL_HOST}:/models",
    "-p", "${PORT}:${PORT}",
    "--shm-size=4g",
    $IMAGE,
    "vllm", "serve", $MODEL_CONTAINER, "--omni", "--port", $PORT,
    "--gpu-memory-utilization", "0.5", "--trust-remote-code"
)
docker @runArgs

Write-Host "启动命令已下发。查看日志: docker logs -f $CONTAINER"
