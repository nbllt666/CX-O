@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo CX-O-SERVER 启动脚本
echo ========================================

REM D1 修复：start-all.bat 引用本文件但此前不存在，导致一键启动必失败。
REM 使用项目根 venv 解释器（py311），与 create-env.bat 保持一致。

if not exist "..\py311\Scripts\python.exe" (
    echo [错误] 未找到 ..\py311 虚拟环境，请先在项目根目录运行 create-env.bat
    pause
    exit /b 1
)

..\py311\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000

pause
