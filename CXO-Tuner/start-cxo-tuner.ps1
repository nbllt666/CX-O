# 启动 CXO-Tuner 独立微调服务（监听 8300 端口）
# 用法：在 CXO-Tuner 目录下运行  .\start-cxo-tuner.ps1
Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)

Write-Host "启动 CXO-Tuner (http://0.0.0.0:8300) ..." -ForegroundColor Cyan

uvicorn tuner.main:app --host 0.0.0.0 --port 8300