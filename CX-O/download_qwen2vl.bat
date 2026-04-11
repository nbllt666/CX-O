@echo off
chcp 65001 > nul
setlocal

set "CONDA_PATH=C:\ProgramData\anaconda3"
set "MODEL_DIR=C:\CX-O\CX-O\models\Qwen"
set "REPO_ID=Qwen/Qwen2-VL-7B-Instruct"

echo ========================================
echo 下载 Qwen2-VL-7B-Instruct 模型 (支持视频)
echo ========================================
echo.
echo 模型: %REPO_ID%
echo 保存路径: %MODEL_DIR%
echo.
echo 特性:
echo - 支持图片理解
echo - 支持视频理解 (自动抽帧)
echo - 最大上下文：16K tokens
echo.
echo 提示：模型约 8GB，使用镜像站下载
echo.

"%CONDA_PATH%\python.exe" -c "
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HOME'] = r'%MODEL_DIR%'

from huggingface_hub import snapshot_download

print('开始下载 Qwen2-VL-7B-Instruct 模型...')
print(f'存储路径：{os.environ.get(\"HF_HOME\")}')
print()

try:
    snapshot_download(
        repo_id='%REPO_ID%',
        local_dir=os.environ['HF_HOME']
    )
    print()
    print('模型下载完成！')
except Exception as e:
    print(f'下载失败：{e}')
"

echo.
pause
