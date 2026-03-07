@echo off
echo Starting F5-TTS service on port 8002...
set PATH=%~dp0ffmpeg-8.0.1-full_build-shared\bin;%PATH%
set HF_HOME=%~dp0F5-TTS\hf_download
set HF_HUB_ENABLE_HF_TRANSFER=1
set HF_ENDPOINT=https://hf-mirror.com
cd /d "%~dp0F5-TTS"
"%~dp0Miniconda3\python.exe" -m uvicorn webapi:app --host 0.0.0.0 --port 8002
pause
