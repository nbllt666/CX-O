# Qwen3-TTS Base 降级运行时部署脚本（Task 2 交付物：GPU1 启动 / 端口 8093 / Base 模型）
# 用法: powershell -ExecutionPolicy Bypass -File start-qwen3-base.ps1
# 前提: vllm/vllm-omni:latest 已拉取; C:\CX-O\models\Qwen3-TTS-12Hz-1.7B-Base 已下载
$ErrorActionPreference = "Stop"

$IMAGE = "vllm/vllm-omni:latest"
$CONTAINER = "qwen3-tts-base"
$PORT = "8093"
$MODEL_HOST = "C:\CX-O\models"
$MODEL_NAME = "Qwen3-TTS-12Hz-1.7B-Base"
$MODEL_CONTAINER = "/models/$MODEL_NAME"

# 已存在则先停旧容器（保留日志重建）
$existing = docker ps -a --format "{{.Names}}"
if ($existing -contains $CONTAINER) {
    Write-Host "清理旧容器 $CONTAINER"
    docker rm -f $CONTAINER
}

Write-Host "启动 $CONTAINER (GPU1 / port $PORT / $MODEL_NAME)"
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
    "--gpu-memory-utilization", "0.5", "--trust-remote-code",
    "--served-model-name", "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
)
docker @runArgs

Write-Host "启动命令已下发。查看日志: docker logs -f $CONTAINER"
