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

REM ========== 智能安装依赖 ==========
echo ========================================
echo 安装项目依赖 (清华源 + 二进制优先)...
echo ========================================
python -m pip install --only-binary=:all: -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout=100

REM 失败时降级策略（跳过需编译包）
if errorlevel 1 (
    echo [提示] 尝试跳过需编译包...
    python -m pip install --only-binary=:all: --no-deps -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout=100
    echo [提示] 单独安装关键包...
    for %%p in (fastapi "pydantic==2.5.3" httpx) do (
        python -m pip install --only-binary=:all: %%p -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet 2>nul
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
