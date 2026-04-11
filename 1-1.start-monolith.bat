@echo off
chcp 65001 > nul
title CX-O v4 Monolith - Start Server

echo ========================================
echo CX-O v4 Monolithic Architecture
echo ========================================

set "ROOT_DIR=%~dp0"
set "PYTHON_EXE=%ROOT_DIR%Miniconda3\python.exe"

if not exist "%PYTHON_EXE%" (
    echo ERROR: Python not found: %PYTHON_EXE%
    echo Please ensure Miniconda3 is installed at %ROOT_DIR%Miniconda3
    pause
    exit /b 1
)

echo Using Python: %PYTHON_EXE%

echo.
echo ========================================
echo Starting CX-O Server (Port 8100)
echo ========================================
echo.
echo NOTE: This starts the monolithic v4 architecture.
echo       All services (ASR, TTS, LLM, Memory) run in a single process.
echo.
echo Service URLs:
echo   - CX-O Server:    ws://127.0.0.1:8100
echo   - Health Check:   http://127.0.0.1:8100/health
echo.
echo ========================================
echo.

cd /d %ROOT_DIR%cx-o\server
"%PYTHON_EXE%" main.py

pause
