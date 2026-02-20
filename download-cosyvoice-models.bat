@echo off
chcp 65001 > nul

echo ========================================
echo Installing ModelScope SDK...
echo ========================================

cd /d %~dp0

Miniconda3\python.exe -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple

echo ========================================
echo Now downloading CosyVoice models...
echo ========================================

cd CosyVoice
..\Miniconda3\python.exe download_models.py

echo ========================================
echo Done!
echo ========================================
pause
