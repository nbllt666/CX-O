@echo off
chcp 65001 > nul
setlocal

set "CONDA_PATH=C:\ProgramData\anaconda3"
set "MODEL_DIR=C:\CX-O\CX-O\models\THUDM\glm-4v-9b-flash"
set "REPO_ID=THUDM/glm-4v-9b-flash"

echo ========================================
echo 下载 GLM-4V-9B-Flash 模型 (支持视频)
echo ========================================
echo.
echo 模型： %REPO_ID%
echo 保存路径： %MODEL_DIR%
echo.
echo 特性:
echo - 支持图片理解
echo - 支持视频理解 (自动抽帧)
echo - Flash 版本，推理速度更快
echo - 最大上下文：16K tokens
echo.
echo 提示：模型约 8GB，使用镜像站下载
echo.

"%CONDA_PATH%\python.exe" "%~dp0download_glm4v_model.py"

echo.
pause
