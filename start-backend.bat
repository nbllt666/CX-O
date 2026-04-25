@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo CXHMS Backend 启动脚本
echo ========================================

REM 检查 Python 是否安装
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

REM 检查依赖
echo.
echo [1/3] 检查依赖...
pip show uvicorn > nul 2>&1
if errorlevel 1 (
    echo [警告] uvicorn 未安装，正在安装...
    pip install uvicorn
)

REM 设置环境变量
set PYTHONPATH=%CD%

REM 启动后端
echo.
echo [2/3] 启动后端服务 (端口 8100)...
echo [3/3] 按 Ctrl+C 停止服务
echo.

python -m backend

pause
