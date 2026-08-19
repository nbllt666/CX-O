# CosyVoice3 主运行时部署脚本（Task 7 变更：CosyVoice2 -> Fun-CosyVoice3-0.5B-2512）
# 用法: powershell -ExecutionPolicy Bypass -File start-cosyvoice.ps1
# 前提: cosyvoice conda 环境（Python 3.10 + torch 2.11+cu128）；模型已下载 C:\CX-O\models\Fun-CosyVoice3-0.5B-2512
# 说明:
#   - CUDA_VISIBLE_DEVICES=1 显式锁定物理 GPU1（与 Qwen3-TTS Base 8093 / VoiceDesign 8091 共置）
#   - --device cuda:0 在 CUDA_VISIBLE_DEVICES=1 下指物理 GPU1
#   - 默认启动预热（把 CUDA/cuDNN 一次性开销移到启动期，消除首包慢速）
#   - --stream-hop-len 10 降低流式首包延迟；CosyVoice3 的 CUDA graph + 采样向量化自动生效
$ErrorActionPreference = "Stop"

$PY = "C:\Users\NBLLT666\.conda\envs\cosyvoice\python.exe"
$SERVER = "C:\CX-O\docker\llm\cosyvoice_server.py"
$LOG = "C:\CX-O\docker\llm\cosyvoice.log"
$MODEL_DIR = "C:\CX-O\models\Fun-CosyVoice3-0.5B-2512"
$PORT = "8094"

$env:CUDA_VISIBLE_DEVICES = "1"
$env:PATH = "C:\Users\NBLLT666\.conda\envs\cosyvoice;C:\Users\NBLLT666\.conda\envs\cosyvoice\Scripts;$env:PATH"
# torch.compile 持久化缓存目录
$env:TORCHINDUCTOR_CACHE_DIR = "C:\CX-O\docker\llm\compile_cache"
$env:TRITON_CACHE_DIR = "C:\CX-O\docker\llm\compile_cache\triton"

Write-Host "启动 CosyVoice3-0.5B (GPU1 / port $PORT / fp16 / warmup) 日志 -> $LOG"
& $PY $SERVER `
    --model_dir $MODEL_DIR `
    --host 127.0.0.1 `
    --port $PORT `
    --device cuda:0 `
    --bf16 `
    --stream-hop-len 10 `
    --flow-steps 3 2>&1 | Tee-Object -FilePath $LOG
