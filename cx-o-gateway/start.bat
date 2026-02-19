@echo off
chcp 65001 >nul
echo ========================================
echo CX-O Gateway 启动脚本
echo ========================================
echo.

cd /d "%~dp0"

echo 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请确保 Python 已安装并添加到 PATH
    pause
    exit /b 1
)

echo 检查依赖...
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo 安装依赖...
    pip install -r requirements.txt
)

echo.
echo 启动 CX-O Gateway (端口 8100)...
echo.
python main.py

pause
