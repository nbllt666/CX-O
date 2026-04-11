@echo off
chcp 65001 > nul
setlocal

set "CONDA_PATH=C:\ProgramData\anaconda3"
set "PYTHON_EXE=%CONDA_PATH%\python.exe"

REM 设置 HuggingFace 镜像
set HF_ENDPOINT=https://hf-mirror.com
set HF_HOME=C:\CX-O\CX-O\F5-TTS\hf_download
set HF_HUB_ENABLE_HF_TRANSFER=1

echo ========================================
echo 下载 F5-TTS 模型
echo ========================================
echo 存储路径: %HF_HOME%
echo.

"%PYTHON_EXE%" -c "
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HOME'] = r'%HF_HOME%'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '1'

from huggingface_hub import snapshot_download

print('正在下载 F5-TTS 模型...')
print(f'HF_ENDPOINT: {os.environ.get(\"HF_ENDPOINT\")}')
print(f'HF_HOME: {os.environ.get(\"HF_HOME\")}')

try:
    snapshot_download(
        repo_id='SWivid/E2-TTS-Base',
        cache_dir=os.environ['HF_HOME']
    )
    print('F5-TTS 模型下载完成！')
except Exception as e:
    print(f'下载失败: {e}')
"

echo.
pause
