@echo off
chcp 65001 > nul
setlocal

set "CONDA_PATH=C:\ProgramData\anaconda3"

echo ========================================
echo 安装 CX-O conda 环境依赖
echo ========================================

echo.
echo [1/3] 安装基础依赖...
"%CONDA_PATH%\Scripts\conda.exe" install -n cx-o -c conda-forge -y fastapi uvicorn websockets pydantic pydantic-settings python-multipart pyyaml orjson httpx aiofiles numpy scipy

echo.
echo [2/3] 安装语音处理依赖...
"%CONDA_PATH%\Scripts\conda.exe" install -n cx-o -c conda-forge -y librosa soundfile

echo.
echo [3/3] 安装工具依赖...
"%CONDA_PATH%\Scripts\conda.exe" install -n cx-o -y jieba pypinyin

echo.
echo ========================================
echo 依赖安装完成！
echo ========================================
pause
