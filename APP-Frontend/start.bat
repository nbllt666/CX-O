@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo CXO-Pet 桌宠应用 启动脚本
echo ========================================

where npm > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 npm，请先安装 Node.js
    pause
    exit /b 1
)

if not exist "node_modules\" (
    echo 正在安装依赖（首次较慢，请耐心等待）...
    npm install
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

if "%1"=="browser" (
    echo 正在以浏览器模式启动（无 Electron 窗口）...
    npm run dev:browser
) else (
    echo 正在以 Electron 桌面模式启动（默认：桌宠悬浮窗）...
    npm run dev
)

pause
