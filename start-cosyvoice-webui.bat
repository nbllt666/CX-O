@echo off
chcp 65001 > nul

echo ========================================
echo Starting CosyVoice WebUI...
echo ========================================

cd /d %~dp0CosyVoice

REM Set PYTHONPATH
set PYTHONPATH=%~dp0CosyVoice

REM Start webui with Fun-CosyVoice3-0.5B (recommended)
..\Miniconda3\python.exe webui.py --port 50000 --model_dir pretrained_models/Fun-CosyVoice3-0.5B

pause
