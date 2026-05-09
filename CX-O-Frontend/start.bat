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

echo 正在启动前端开发服务器...
npm run dev

pause
