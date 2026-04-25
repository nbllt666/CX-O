@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

echo ========================================
echo CXHMS 一键启动脚本
echo ========================================
echo.

cd /d "%~dp0"

REM 检查 Python
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

REM 检查依赖
echo [检查依赖]
pip show uvicorn > nul 2>&1
if errorlevel 1 (
    echo [警告] uvicorn 未安装，正在安装...
    pip install uvicorn
)

REM 创建 logs 目录
if not exist "logs" mkdir logs

REM 设置环境变量
set PYTHONPATH=%CD%

REM 启动后端服务
echo.
echo [启动后端服务 - 端口 8100]
start "CXHMS-Backend" cmd /c "python -m backend > logs\backend.log 2>&1"

REM 等待后端启动
echo [等待后端启动...]
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":8100" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [后端已启动]
        goto :start_gateway
    )
)
echo [警告] 后端启动超时，继续启动其他服务...

:start_gateway
REM 启动 Gateway
echo.
echo [启动 Gateway - 端口 8100]
cd gateway
start "CXHMS-Gateway" cmd /c "python run.py > ..\logs\gateway.log 2>&1"
cd ..

REM 等待 Gateway 启动
echo [等待 Gateway 启动...]
for /L %%i in (1,1,20) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":8100" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [Gateway 已启动]
        goto :start_frontend
    )
)

:start_frontend
REM 启动前端
echo.
echo [启动前端服务 - 端口 3000]
cd frontend
start "CXHMS-Frontend" cmd /c "npm run dev > ..\logs\frontend.log 2>&1"
cd ..

REM 等待前端启动
echo [等待前端启动...]
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":3000" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [前端已启动]
        goto :check_complete
    )
)

:check_complete
echo.
echo ========================================
echo 所有服务已启动
echo ========================================
echo.
echo 服务地址:
echo   - 前端:   http://localhost:3000
echo   - 后端:   http://localhost:8100
echo   - Gateway: http://localhost:8100
echo.
echo 日志文件: logs\
echo   - backend.log
echo   - gateway.log
echo   - frontend.log
echo.
echo 按任意键打开浏览器...
pause > nul

start http://localhost:3000

echo.
echo 按任意键关闭所有服务...
pause > nul

taskkill /F /IM node.exe > nul 2>&1
taskkill /F /IM python.exe > nul 2>&1

echo [服务已关闭]
pause
