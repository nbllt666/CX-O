@echo off
chcp 65001 > nul
setlocal

set "CONDA_PATH=C:\ProgramData\anaconda3"
set "PYTHON_EXE=%CONDA_PATH%\python.exe"

REM 使用官方 HuggingFace
set HF_ENDPOINT=https://huggingface.co
set HF_HOME=C:\CX-O\CX-O\SenseVoice\models

echo ========================================
echo 下载 SenseVoice 模型
echo ========================================
echo 存储路径: %HF_HOME%
echo 注意: 需要网络能访问 huggingface.co
echo.

"%PYTHON_EXE%" -c "
import os
os.environ['HF_ENDPOINT'] = 'https://huggingface.co'
os.environ['HF_HOME'] = r'%HF_HOME%'

from huggingface_hub import snapshot_download

print('正在下载 SenseVoice 模型...')
print(f'HF_ENDPOINT: {os.environ.get(\"HF_ENDPOINT\")}')
print(f'HF_HOME: {os.environ.get(\"HF_HOME\")}')

try:
    snapshot_download(
        repo_id='iic/SenseVoiceSmall',
        cache_dir=os.environ['HF_HOME']
    )
    print('SenseVoice 模型下载完成！')
except Exception as e:
    print(f'下载失败: {e}')
"

echo.
pause
