@echo off
chcp 65001 > nul

echo ========================================
echo 创建新虚拟环境...
echo ========================================
call Miniconda3\Scripts\conda create -n project_fix python=3.10 -y
call Miniconda3\Scripts\conda activate project_fix

echo ========================================
echo 更新基础工具...
echo ========================================
pip install -U pip setuptools wheel --quiet

echo ========================================
echo 安装项目依赖...
echo ========================================
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout=100

REM 检查是否仍有错误
if %errorlevel% neq 0 (
    echo.
    echo ========================================
    echo 部分依赖安装失败，尝试单独安装有问题的包...
    echo ========================================
    
    REM 尝试单独安装可能有问题的包
    pip install pydantic==2.5.3 --quiet
)

echo.
echo ========================================
echo 安装完成！请检查版本兼容性
echo 使用以下命令验证:
echo pip list ^| findstr /i "fastapi pydantic httpx"
echo ========================================
pause
