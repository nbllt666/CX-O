@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

REM The versioned manifest records PID + creation time + exact command.
REM Legacy TEMP\cxo_pids.txt contains no ownership proof and is not consumed.
set "PYTHON_EXE=python"
if exist "%~dp0py311\Scripts\python.exe" set "PYTHON_EXE=%~dp0py311\Scripts\python.exe"
"%PYTHON_EXE%" -c "import psutil" > nul 2>&1
if errorlevel 1 (
    echo [错误] 请先安装项目 Python 依赖（包括 psutil）。
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)
"%PYTHON_EXE%" "%~dp0tools\service_processes.py" stop
set "STOP_RESULT=%ERRORLEVEL%"
if /i not "%~1"=="--no-pause" pause
exit /b %STOP_RESULT%
