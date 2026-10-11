@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist "%~dp0py311\Scripts\python.exe" set "PYTHON_EXE=%~dp0py311\Scripts\python.exe"
"%PYTHON_EXE%" -c "import psutil" > nul 2>&1
if errorlevel 1 (
    echo [错误] 请先安装项目 Python 依赖（包括 psutil）。
    pause
    exit /b 1
)

echo ========================================
echo CX-O 一键启动脚本
echo 服务日志保存在 logs 目录
echo ========================================
REM Only the helper's returned launcher identities are recorded.
REM Pre-existing port listeners are never adopted or stopped.
set "START_FAILED=0"
for %%s in (server voice model frontend) do (
    "%PYTHON_EXE%" "%~dp0tools\service_processes.py" start %%s
    if errorlevel 1 set "START_FAILED=1"
)
if "%START_FAILED%"=="0" (
    echo [启动检查完成]
) else (
    echo [部分服务未就绪，请查看上方提示与 logs 目录]
)
echo.
echo 前端地址: http://localhost:3100
echo 按任意键打开浏览器...
pause > nul
start "" http://localhost:3100
echo.
echo 按任意键停止本项目启动的服务...
pause > nul
call "%~dp0stop-all.bat" --no-pause
pause
