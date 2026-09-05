# 启动 CXO-Tuner 独立微调服务（监听 8310 端口；8300 已归 CXO-ModelStation，勿改回）
# 用法：在 CXO-Tuner 目录下运行  .\start-cxo-tuner.ps1
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "启动 CXO-Tuner (http://0.0.0.0:8310) ..." -ForegroundColor Cyan

uvicorn tuner.main:app --host 0.0.0.0 --port 8310
