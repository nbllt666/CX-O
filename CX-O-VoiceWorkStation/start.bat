@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ========================================
echo CX-O-VoiceWorkStation 启动脚本
echo ========================================

REM X1 修复：启动口径与 CX-O-SERVER 对齐——优先项目根 py311 虚拟环境；
REM py311 缺失时回退全局 python（回退策略比 SERVER 宽松，不硬失败，
REM 避免破坏已有全局环境的用户），最后 pause 保持窗口。

set "PYTHON_EXE="
if exist "%~dp0..\py311\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\py311\Scripts\python.exe"
    echo [信息] 使用项目虚拟环境 ..\py311
) else (
    echo [警告] 未找到 ..\py311\Scripts\python.exe，回退使用全局 python
    python --version > nul 2>&1
    if errorlevel 1 (
        echo [错误] 未找到 Python，请安装 Python 或先在项目根目录运行 create-env.bat
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python"
)

set PYTHONPATH=%CD%\..

%PYTHON_EXE% -m workstation.main

pause
