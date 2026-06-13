@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo CX-O-Frontend 启动脚本
echo ========================================

where npm > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 npm
    pause
    exit /b 1
)

if not exist "node_modules\" (
    echo 正在安装依赖...
    npm install
)

if "%1"=="electron" (
    echo 正在以 Electron 模式启动...
    npm run dev
) else (
    echo 正在以浏览器模式启动...
    npm run dev
)

pause
