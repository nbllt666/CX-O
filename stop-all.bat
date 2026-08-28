@echo off
chcp 65001 > nul
setlocal

REM CX-O 一键停止脚本：读取 start-all.bat 记录的服务 PID 文件，逐个按 PID 杀进程树精确停止。
REM PID 文件路径与 start-all.bat 的 PID_FILE 变量一致（用户 TEMP 目录下 cxo_pids.txt）。
REM 用途：
REM   1. 独立停止入口——服务启动超时的"孤儿"或日常停止，双击或命令行均可直接调用；
REM   2. start-all.bat 末尾交互停止逻辑保持独立实现（最小改动），本脚本不被其 call，
REM      如后续需要复用，去掉末尾 pause 后可由 start-all.bat 直接 call。
REM 停止完成后清理 PID 记录文件，避免残留 PID 被复用后误杀无关进程。

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

for /f "usebackq delims=" %%p in ("%PID_FILE%") do (
    taskkill /PID %%p /T /F > nul 2>&1
    if not errorlevel 1 (
        echo [已停止] PID %%p
        set /a STOP_OK+=1
    ) else (
        echo [停止失败或进程不存在] PID %%p
        set /a STOP_FAIL+=1
    )
)

REM 全部处理完后清理 PID 记录文件
del /f /q "%PID_FILE%" > nul 2>&1

echo.
echo [停止结果] 成功 %STOP_OK% 个，失败/不存在 %STOP_FAIL% 个，PID 记录已清理。
pause
exit /b 0
