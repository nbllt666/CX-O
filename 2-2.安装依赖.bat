@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

REM ========== 智能定位 Miniconda ==========
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
if exist "%SCRIPT_DIR%\Miniconda3\Scripts\conda.exe" (
    set "MINICONDA_PATH=%SCRIPT_DIR%\Miniconda3"
) else if exist "%SCRIPT_DIR%\..\Miniconda3\Scripts\conda.exe" (
    set "MINICONDA_PATH=%SCRIPT_DIR%\..\Miniconda3"
) else (
    echo [!] 未找到 Miniconda3！请将脚本放在与 Miniconda3 同级目录
    pause & exit /b 1
)

REM ========== 环境隔离 ==========
set "PATH=%MINICONDA_PATH%;%MINICONDA_PATH%\Scripts;%MINICONDA_PATH%\Library\bin;%PATH%"
call "%MINICONDA_PATH%\Scripts\activate.bat" "%MINICONDA_PATH%"

echo ========================================
echo 使用 base 环境 (路径: %MINICONDA_PATH%)
echo ========================================
call conda activate base

REM ========== 安装 PyTorch CUDA 版本 ==========
echo ========================================
echo 安装 PyTorch (CUDA 12.8)...
echo ========================================
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

REM ========== 智能安装依赖 ==========
echo ========================================
echo 安装项目依赖 (清华源优先)...
echo ========================================
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout=10000

REM 失败时切换官方源重试
if errorlevel 1 (
    echo [提示] 清华源失败，切换官方 PyPI 源重试...
    python -m pip install -r requirements.txt -i https://pypi.org/simple/ --timeout=10000
)

REM 仍失败则降级策略（逐个安装关键包）
if errorlevel 1 (
    echo [提示] 逐个安装关键包...
    for %%p in (numpy fastapi pydantic httpx jieba pypinyin transformers accelerate librosa soundfile) do (
        echo 安装 %%p...
        python -m pip install %%p -i https://pypi.org/simple/ --quiet 2>nul
    )
)

echo.
echo ========================================
echo [OK] 依赖安装完成！
echo ========================================
endlocal
pause
