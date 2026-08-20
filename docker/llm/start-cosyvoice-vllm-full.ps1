# CosyVoice3 + vLLM（Docker，自包含镜像）启动脚本
# 用法: powershell -ExecutionPolicy Bypass -File start-cosyvoice-vllm-full.ps1
# 说明:
#   - 使用已烤入模型的镜像 cosyvoice-vllm-full:latest（无需 -v 卷挂载，端口为容器内默认 8094）
#   - 构建: 见 Dockerfile.cosyvoice-vllm.full 头部命令
#   - 首块优化参数（与挂载版 start-cosyvoice-vllm.ps1 一致）:
#     --flow-steps 1 + --flow-cfg-rate 0（首块 <=400ms）
#   - GPU1（CUDA_VISIBLE_DEVICES=1）。GPU0 被 vllm-gemma4(8002) 占满显存。
#   - tmp/assets 覆盖为容器内路径（cosyvoice_server.py 默认值是 Windows 路径）
$ErrorActionPreference = "Stop"

$IMAGE = "cosyvoice-vllm-full:latest"
$CONTAINER = "cosyvoice-vllm-full"
$PORT = "8094"

# 已存在则先停旧容器
$existing = docker ps -a --format "{{.Names}}"
if ($existing -contains $CONTAINER) {
    Write-Host "清理旧容器 $CONTAINER"
    docker rm -f $CONTAINER
}

Write-Host "启动 $CONTAINER (GPU1 / port $PORT / CosyVoice3 + vLLM in-process / 模型已内置)"
$runArgs = @(
    "run", "-d",
    "--name", $CONTAINER,
    "--gpus", "all",
    "-e", "CUDA_VISIBLE_DEVICES=1",
    "-p", "${PORT}:${PORT}",
    "--shm-size=4g",
    $IMAGE,
    "python", "/workspace/server.py",
    "--host", "0.0.0.0",
    "--port", $PORT,
    "--device", "cuda:0",
    "--bf16",
    "--stream-hop-len", "5",
    "--flow-steps", "1",
    "--flow-cfg-rate", "0",
    "--vllm",
    "--tmp_dir", "/tmp",
    "--assets_dir", "/tmp"
)
docker @runArgs

Write-Host "启动命令已下发。查看日志: docker logs -f $CONTAINER"