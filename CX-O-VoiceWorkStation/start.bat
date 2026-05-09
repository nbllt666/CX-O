@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo CX-O-VoiceWorkStation 启动脚本
echo ========================================

python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python
    pause
    exit /b 1
)

set PYTHONPATH=%CD%\..

python -m workstation.main

pause
