@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

echo ========================================
echo CX-O 一键启动脚本
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

REM 创建 logs 目录
if not exist "logs" mkdir logs

REM ==========================================
REM 启动 CX-O-SERVER
REM ==========================================
echo.
echo [启动 CX-O-SERVER - 端口 8100]
cd CX-O-SERVER
start "CX-O-SERVER" cmd /c "start.bat"
cd ..

echo [等待 CX-O-SERVER 启动...]
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":8100" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [CX-O-SERVER 已启动]
        goto :start_voiceworkstation
    )
)
echo [警告] CX-O-SERVER 启动超时，继续启动其他服务...

REM ==========================================
REM 启动 CX-O-VoiceWorkStation
REM ==========================================
:start_voiceworkstation
echo.
echo [启动 CX-O-VoiceWorkStation - 端口 8200]
cd CX-O-VoiceWorkStation
start "CX-O-VoiceWorkStation" cmd /c "start.bat"
cd ..

echo [等待 CX-O-VoiceWorkStation 启动...]
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":8200" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [CX-O-VoiceWorkStation 已启动]
        goto :start_frontend
    )
)
echo [警告] CX-O-VoiceWorkStation 启动超时，继续启动其他服务...

REM ==========================================
REM 启动 CX-O-Frontend
REM ==========================================
:start_frontend
echo.
echo [启动 CX-O-Frontend - 端口 3000]
cd CX-O-Frontend
start "CX-O-Frontend" cmd /c "start.bat"
cd ..

echo [等待 CX-O-Frontend 启动...]
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":3000" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [CX-O-Frontend 已启动]
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
echo   - 前端:             http://localhost:3000
echo   - CX-O-SERVER:      http://localhost:8100
echo   - VoiceWorkStation: http://localhost:8200
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
