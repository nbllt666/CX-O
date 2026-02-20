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

REM ========== 核心修复：清除破坏性文件 ==========
set "SITE_PACKAGES=%CONDA_PREFIX%\Lib\site-packages"
if exist "%SITE_PACKAGES%\distutils-precedence.pth" (
    echo [修复] 清理损坏的 distutils-precedence.pth...
    del /f /q "%SITE_PACKAGES%\distutils-precedence.pth" >nul 2>&1
    if exist "%SITE_PACKAGES%\_distutils_hack" rmdir /s /q "%SITE_PACKAGES%\_distutils_hack" >nul 2>&1
)

REM ========== 安全更新工具链（仅升级，不卸载！）==========
echo [修复] 重置构建工具...
python -m pip install --upgrade "setuptools>=68.0.0" "pip>=23.0" "wheel" --quiet --no-warn-script-location

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

REM ========== 验证 ==========
echo.
echo ========================================
echo 环境验证
echo ========================================
python -c "import sys; print(f'Python: {sys.version}')" 
python -m pip list --format=columns | findstr /i "pip setuptools wheel fastapi pydantic httpx"
echo.
echo [OK] base 环境就绪！
echo.
echo 注意事项:
echo   • 已永久删除损坏的 distutils-precedence.pth
echo   • 所有操作仅限本项目 Miniconda，无系统污染
echo   • 需编译包请安装 VS Build Tools (非必需)
echo ========================================
endlocal
pause
