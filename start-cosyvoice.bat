@echo off
chcp 65001 > nul
title CosyVoice FastAPI Service

echo ========================================
echo CosyVoice FastAPI Service
echo ========================================

set "ROOT_DIR=%~dp0"
set "PYTHON_EXE=%ROOT_DIR%Miniconda3\python.exe"
set "COSYVOICE_DIR=%ROOT_DIR%CosyVoice"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found: %PYTHON_EXE%
    echo Please ensure Miniconda3 is installed at %ROOT_DIR%Miniconda3
    pause
    exit /b 1
)

if not exist "%COSYVOICE_DIR%" (
    echo ERROR: CosyVoice directory not found: %COSYVOICE_DIR%
    echo Please clone CosyVoice repository first
    pause
    exit /b 1
)

echo Using Python: %PYTHON_EXE%
echo CosyVoice Dir: %COSYVOICE_DIR%
echo.

cd /d "%COSYVOICE_DIR%"

echo Starting CosyVoice FastAPI Server on port 8003...
echo Model: CosyVoice2-0.5B
echo.
echo Service URL: http://127.0.0.1:8003
echo API Endpoints:
echo   - POST /inference_sft
echo   - POST /inference_zero_shot
echo   - POST /inference_cross_lingual
echo   - POST /inference_instruct
echo   - POST /inference_instruct2
echo.

"%PYTHON_EXE%" runtime/python/fastapi/server.py --port 8003 --model_dir pretrained_models/CosyVoice2-0.5B

pause
