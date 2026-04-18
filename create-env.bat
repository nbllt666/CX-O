@echo off
chcp 65001 >nul
echo ========================================
echo CX-O Python 环境创建脚本
echo ========================================
echo.

:: 检查 Python 版本
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.11+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 获取 Python 版本
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo 当前 Python 版本: %PYTHON_VERSION%

:: 提取主版本号
set MAJOR_VERSION=%PYTHON_VERSION:~0,1%
set MINOR_VERSION=%PYTHON_VERSION:~2,2%

:: 检查是否为 3.11+
if %MAJOR_VERSION% LSS 3 (
    echo [错误] 需要 Python 3.11 或更高版本
    pause
    exit /b 1
)

if %MAJOR_VERSION% EQU 3 (
    if %MINOR_VERSION% LSS 11 (
        echo [错误] 需要 Python 3.11 或更高版本，当前版本: %PYTHON_VERSION%
        pause
        exit /b 1
    )
)

echo [检查通过] Python 版本符合要求
echo.

:: 检查是否已存在虚拟环境
if exist "py311" (
    echo [警告] py311 虚拟环境已存在
    set /p RECREATE=是否删除并重新创建? (Y/N):
    if /i "%RECREATE%"=="Y" (
        echo 删除现有虚拟环境...
        rd /s /q py311
        echo 删除完成
    ) else (
        echo 使用现有虚拟环境
        set /p ACTIVATE=是否激活现有环境? (Y/N):
        if /i "%ACTIVATE%"=="Y" (
            call py311\Scripts\activate.bat
            echo 环境已激活
            pip --version
        )
        pause
        exit /b 0
    )
)

echo.
echo 正在创建虚拟环境 py311...
python -m venv py311

if errorlevel 1 (
    echo [错误] 创建虚拟环境失败
    pause
    exit /b 1
)

echo.
echo 正在激活虚拟环境...
call py311\Scripts\activate.bat

echo.
echo 正在升级 pip...
python -m pip install --upgrade pip

echo.
echo ========================================
echo 环境创建完成！
echo ========================================
echo.
echo 虚拟环境位置: %CD%\py311
echo 激活命令: call py311\Scripts\activate.bat
echo.
echo 下一步操作:
echo 1. 激活环境: call py311\Scripts\activate.bat
echo 2. 安装依赖: pip install -r requirements.txt
echo.
echo.

:: 询问是否立即安装依赖
set /p INSTALL_DEPS=是否立即安装依赖? (Y/N):
if /i "%INSTALL_DEPS%"=="Y" (
    echo.
    echo 正在安装依赖...
    pip install -r requirements.txt

    if errorlevel 1 (
        echo [警告] 依赖安装过程中出现错误
        echo 请手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )

    echo.
    echo ========================================
    echo 依赖安装完成！
    echo ========================================
    echo.
    echo 现在可以运行项目了！
)
echo.
pause
