@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM 服务 PID 记录文件（精确停止专用，避免 taskkill /IM python.exe 误杀全机 Python 进程）
set "PID_FILE=%TEMP%\cxo_pids.txt"
if exist "%PID_FILE%" del /f /q "%PID_FILE%" > nul 2>&1

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
echo [启动 CX-O-SERVER - 端口 8000]
cd CX-O-SERVER
start "CX-O-SERVER" cmd /c "start.bat"
cd ..

echo [等待 CX-O-SERVER 启动...]
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":8000" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [CX-O-SERVER 已启动]
        call :record_pid 8000
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
        call :record_pid 8200
        goto :start_frontend
    )
)
echo [警告] CX-O-VoiceWorkStation 启动超时，继续启动其他服务...

REM ==========================================
REM 启动 APP-Frontend（浏览器模式，替代原 CX-O-Frontend）
REM ==========================================
:start_frontend
echo.
echo [启动 APP-Frontend - 端口 3100]
cd APP-Frontend
start "APP-Frontend" cmd /c "start.bat browser"
cd ..

echo [等待 APP-Frontend 启动...]
for /L %%i in (1,1,30) do (
    ping -n 2 127.0.0.1 > nul 2>&1
    netstat -an | findstr ":3100" | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [APP-Frontend 已启动]
        call :record_pid 3100
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
echo   - 前端:             http://localhost:3100
echo   - CX-O-SERVER:      http://localhost:8000
echo   - VoiceWorkStation: http://localhost:8200
echo.
echo 按任意键打开浏览器...
pause > nul

start http://localhost:3100

echo.
echo 按任意键关闭所有服务...
pause > nul

REM 精确停止本脚本启动的服务进程（按 PID 记录逐个杀树，替代误杀全机进程的 taskkill /IM python.exe）
if exist "%PID_FILE%" (
    for /f "usebackq delims=" %%p in ("%PID_FILE%") do (
        taskkill /PID %%p /T /F > nul 2>&1
    )
    del /f /q "%PID_FILE%" > nul 2>&1
)
taskkill /F /IM node.exe > nul 2>&1

echo [服务已关闭]
pause

goto :eof

:record_pid
REM 子例程：将监听指定端口的进程 PID 追加到 PID_FILE（netstat -ano 第5列为 PID）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%~1 " ^| findstr "LISTENING"') do >> "%PID_FILE%" echo %%p
goto :eof
