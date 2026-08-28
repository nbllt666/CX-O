@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM 服务 PID 记录文件（精确停止专用，避免 taskkill /IM python.exe 误杀全机 Python 进程）
REM R8-04：启动时不再清空 PID 文件——残留记录属于上次运行的服务，保留其 PID
REM 可被 stop-all.bat / 末尾停止逻辑一并接管；本次启动成功后新 PID 自然追加。
set "PID_FILE=%TEMP%\cxo_pids.txt"

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
    netstat -an | findstr /c:":8000 " | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [CX-O-SERVER 已启动]
        call :record_pid 8000
        goto :start_voiceworkstation
    )
)
echo [警告] CX-O-SERVER 启动超时，继续启动其他服务...
REM R8-04：超时路径补记 PID——服务可能延迟启动成功，若此刻端口已监听则纳入停止管理
call :record_pid 8000

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
    netstat -an | findstr /c:":8200 " | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [CX-O-VoiceWorkStation 已启动]
        call :record_pid 8200
        goto :start_frontend
    )
)
echo [警告] CX-O-VoiceWorkStation 启动超时，继续启动其他服务...
REM R8-04：超时路径补记 PID——服务可能延迟启动成功，若此刻端口已监听则纳入停止管理
call :record_pid 8200

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
    netstat -an | findstr /c:":3100 " | findstr "LISTENING" > nul 2>&1
    if not errorlevel 1 (
        echo [APP-Frontend 已启动]
        call :record_pid 3100
        goto :check_complete
    )
)
echo [警告] APP-Frontend 启动超时，继续完成启动流程...
REM R8-04：超时路径补记 PID——服务可能延迟启动成功，若此刻端口已监听则纳入停止管理
call :record_pid 3100

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

REM 精确停止本脚本启动的服务进程（按 PID 记录逐个杀树）。
REM D1 修复：移除全局 taskkill /IM node.exe——前端进程已由上方记录的
REM 3100 监听 PID 连同整个进程树一并终止；原先的全局清杀会误伤
REM 用户机器上与本系统无关的其它 Node 进程。
if exist "%PID_FILE%" (
    for /f "usebackq delims=" %%p in ("%PID_FILE%") do (
        taskkill /PID %%p /T /F > nul 2>&1
    )
    del /f /q "%PID_FILE%" > nul 2>&1
)

echo [服务已关闭]
pause

goto :eof

:record_pid
REM 子例程：将监听指定端口的进程 PID 追加到 PID_FILE（netstat -ano 第5列为 PID）
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%~1 " ^| findstr "LISTENING"') do >> "%PID_FILE%" echo %%p
goto :eof
