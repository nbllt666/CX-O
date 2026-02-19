@echo off
chcp 65001 > nul

echo ========================================
echo 正在检测并清理无效包分布...
echo ========================================

REM 定位site-packages目录
set "SITE_PACKAGES=%~dp0Miniconda3\Lib\site-packages"

echo 检测到site-packages路径: %SITE_PACKAGES%

REM 检查并删除所有以连字符开头的无效包
echo 搜索并清理无效包分布...
set count=0

REM 处理无效目录
for /f "delims=" %%i in ('dir /b /ad "%SITE_PACKAGES%\-*" 2^>nul') do (
    echo 删除无效目录: %%i
    rd /s /q "%SITE_PACKAGES%\%%i" >nul 2>&1
    set /a count+=1
)

REM 处理无效文件
for /f "delims=" %%i in ('dir /b "%SITE_PACKAGES%\-*.*" 2^>nul') do (
    echo 删除无效文件: %%i
    del /f /q "%SITE_PACKAGES%\%%i" >nul 2>&1
    set /a count+=1
)

echo 共清理 %count% 个无效包分布

REM 额外检查特定的无效文件
echo 检查并清理特定无效文件...
del /f /q "%SITE_PACKAGES%\[~-]*" >nul 2>&1
del /f /q "%SITE_PACKAGES%\[~-]*.*" >nul 2>&1

echo.
echo ========================================
echo 重新安装关键依赖包...
echo ========================================
Miniconda3\python.exe -m pip install --upgrade --force-reinstall protobuf==4.25.3 pillow==10.4.0

echo.
echo ========================================
echo 尝试从清华镜像源安装依赖...
echo ========================================
Miniconda3\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout=100 --no-cache-dir

if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo 所有依赖已成功安装！
    echo ========================================
    goto end
)

echo.
echo ========================================
echo 部分依赖安装失败，尝试从官方源安装剩余依赖...
echo ========================================
Miniconda3\python.exe -m pip install -r requirements.txt -i https://pypi.org/simple --timeout=100 --no-cache-dir

:end
echo.
echo ========================================
echo 安装过程完成
echo 建议检查以下事项：
echo 1. 依赖冲突: 注意上述错误中提到的版本冲突
echo 2. 如有必要，可尝试手动安装特定版本:
echo    pip install package_name==version
echo 3. 如果问题持续，考虑创建新虚拟环境:
echo    conda create -n new_env python=3.10
echo ========================================
pause