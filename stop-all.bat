@echo off
chcp 65001 > nul
setlocal

REM CX-O one-click stop script.
REM Reads the service PID file recorded by start-all.bat and kills each
REM process tree by PID. PID file path matches start-all.bat's PID_FILE
REM variable (cxo_pids.txt under user TEMP).
REM Covered services (recorded by port): 8000 SERVER / 8200 VoiceWorkStation
REM / 8300 ModelStation / 3100 APP-Frontend. Port-based recording means new
REM services are covered automatically once start-all.bat calls :record_pid.
REM Usage:
REM   1. Standalone stop entry -- for orphan services after start timeout
REM      or daily shutdown; works by double-click or from command line.
REM   2. start-all.bat's interactive stop logic stays independent (minimal
REM      change); this script is not called by it. To reuse, drop the
REM      trailing pause and call it from start-all.bat.
REM PID file is cleaned up after stopping to avoid stale PID reuse kills.
REM PID reuse guard: verify the image name belongs to this project via
REM tasklist before taskkill (whitelist: python.exe/node.exe/electron.exe;
REM start-all.bat :record_pid stores bare PID only). Skip + warn on
REM mismatch so a recycled PID never kills an unrelated process.
REM NOTE: comments in this file stay English -- cmd's parser mangles long
REM UTF-8 REM lines under codepage 65001 (line-splitting bug); Chinese
REM runtime output via echo below is unaffected and kept for UX.

set "PID_FILE=%TEMP%\cxo_pids.txt"

echo ========================================
echo CX-O 一键停止脚本
echo ========================================
echo.

if not exist "%PID_FILE%" (
    echo [提示] 未找到 PID 记录文件，可能服务未由 start-all.bat 启动，或已被停止。
    pause
    exit /b 0
)

set /a STOP_OK=0
set /a STOP_FAIL=0
set /a STOP_SKIP=0

for /f "usebackq delims=" %%p in ("%PID_FILE%") do (
    call :stop_owned_pid %%p
)

REM 全部处理完后清理 PID 记录文件
del /f /q "%PID_FILE%" > nul 2>&1

echo.
echo [停止结果] 成功 %STOP_OK% 个，失败 %STOP_FAIL% 个，跳过（PID 复用防护/已退出）%STOP_SKIP% 个，PID 记录已清理。
pause
exit /b 0

:stop_owned_pid
REM PID ownership guard: kill tree ONLY if image name is in whitelist.
REM Whitelist: python.exe / node.exe / electron.exe (project-owned processes;
REM start-all.bat :record_pid stores bare PID from netstat, no image name).
REM PID reused by another process, or already exited (tasklist prints an
REM INFO line) -> first token not in whitelist -> skip, never kill.
set "TARGET_PID=%~1"
set "PROC_NAME="
for /f "tokens=1" %%n in ('tasklist /FI "PID eq %TARGET_PID%" /NH 2^>nul') do (
    if not defined PROC_NAME set "PROC_NAME=%%n"
)
if /i "%PROC_NAME%"=="python.exe" goto :kill_tree
if /i "%PROC_NAME%"=="node.exe" goto :kill_tree
if /i "%PROC_NAME%"=="electron.exe" goto :kill_tree
echo [跳过] PID %TARGET_PID% 进程已退出或进程名 [%PROC_NAME%] 不属于本项目（PID 复用防护），未终止
set /a STOP_SKIP+=1
goto :eof

:kill_tree
taskkill /PID %TARGET_PID% /T /F > nul 2>&1
if not errorlevel 1 (
    echo [已停止] PID %TARGET_PID% [%PROC_NAME%]
    set /a STOP_OK+=1
) else (
    echo [停止失败] PID %TARGET_PID% [%PROC_NAME%]
    set /a STOP_FAIL+=1
)
goto :eof
