# CosyVoice3 + vLLM（Docker）主运行时部署脚本
# 用法: powershell -ExecutionPolicy Bypass -File start-cosyvoice-vllm.ps1
# 说明:
#   - Docker 容器内 vLLM 进程内引擎（Linux 无 WDDM 开销），CosyVoice3 流式首包 <800ms
#   - 需先构建镜像: docker build -f docker/llm/Dockerfile.cosyvoice-vllm -t cosyvoice-vllm:latest .
#   - vLLM 导出自动完成: 容器启动时 AutoModel(load_vllm=True) 调 export_cosyvoice2_vllm，
#     若 model_dir/vllm/ 已存在则跳过（首次启动自动导出，无需手动脚本）
#   - GPU1（CUDA_VISIBLE_DEVICES=1），端口 8094。
#     ⚠️ GPU0 被 vllm-gemma4(8002) 占满显存，cosyvoice 换到 GPU1 避免 KV cache 初始化失败。
#   - 首块优化参数（2026-08-17 Task B 实测）:
#     --flow-steps 1     : flow decoder ODE 1 步，首块 0.57->0.39s（达标 <=400ms）；需配合 --flow-cfg-rate 0
#     --flow-cfg-rate 0  : 关闭 CFG（batch=1）。⚠️ flow_steps=1 + CFG on 会产生削波/波形断裂 artifact，必须为 0
#     --stream-hop-len 5 : 首 hop 5 token（配合 token_min_hop_len 覆盖）
#   - 回退参数: --flow-steps 3（去掉 --flow-cfg-rate）即恢复 baseline（首块 ~0.57s 但音质最稳）
param(
    # 模型根目录（宿主机侧，容器固定挂载到 /workspace/models；默认值保持原硬编码路径兼容）
    [string]$ModelsPath = "C:\CX-O\models"
)
$ErrorActionPreference = "Stop"

$IMAGE = "cosyvoice-vllm:latest"
$CONTAINER = "cosyvoice-vllm"
$PORT = "8094"
$MODEL_DIR = Join-Path $ModelsPath "Fun-CosyVoice3-0.5B-2512"
$MODEL_CONTAINER = "/workspace/models/Fun-CosyVoice3-0.5B-2512"

# 已存在则先停旧容器
$existing = docker ps -a --format "{{.Names}}"
if ($existing -contains $CONTAINER) {
    Write-Host "清理旧容器 $CONTAINER"
    docker rm -f $CONTAINER
}

Write-Host "启动 $CONTAINER (GPU1 / port $PORT / CosyVoice3 + vLLM in-process)"
$runArgs = @(
    "run", "-d",
    "--name", $CONTAINER,
    "--gpus", "all",
    "-e", "CUDA_VISIBLE_DEVICES=1",
    "-v", "${ModelsPath}:/workspace/models",
    "-p", "${PORT}:${PORT}",
    "--shm-size=4g",
    "--restart", "unless-stopped",
    $IMAGE,
    "python", "/workspace/server.py",
    "--model_dir", $MODEL_CONTAINER,
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