@echo off
chcp 65001 > nul
title CX-O Start All Services

echo ========================================
echo CX-O Microservices - Start All Services
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
echo [1/5] Starting SenseVoice ASR Service (Port 8001)
echo ========================================
set SENSEVOICE_PORT=8001
start "SenseVoice ASR" cmd /k "set SENSEVOICE_PORT=8001 && cd /d %ROOT_DIR%SenseVoice && "%PYTHON_EXE%" api.py"
timeout /t 5 /nobreak > nul

echo.
echo ========================================
echo [2/5] Starting F5-TTS Service (Port 8002)
echo ========================================
start "F5-TTS" cmd /k "set PORT=8002 && cd /d %ROOT_DIR%F5-TTS && "%PYTHON_EXE%" webapi.py"
timeout /t 5 /nobreak > nul

echo.
echo ========================================
echo [3/5] Starting CXHMS Backend Service (Port 8000)
echo ========================================
start "CXHMS Backend" cmd /k "cd /d %ROOT_DIR%CXHMS && "%PYTHON_EXE%" main.py"
timeout /t 8 /nobreak > nul

echo.
echo ========================================
echo [4/5] Starting CX-O Gateway (Port 8100)
echo ========================================
start "CX-O Gateway" cmd /k "cd /d %ROOT_DIR%cx-o-gateway && "%PYTHON_EXE%" main.py"
timeout /t 5 /nobreak > nul

echo.
echo ========================================
echo [5/5] Starting CX-O Frontend (Port 3000)
echo ========================================
start "CX-O Frontend" cmd /k "cd /d %ROOT_DIR%cx-o-frontend && npm run dev"
timeout /t 3 /nobreak > nul

echo.
echo ========================================
echo All services started!
echo ========================================
echo.
echo Service URLs:
echo   - SenseVoice ASR:  http://127.0.0.1:8001
echo   - F5-TTS:          http://127.0.0.1:8002
echo   - CXHMS Backend:   http://127.0.0.1:8000
echo   - CX-O Gateway:    ws://127.0.0.1:8100/ws
echo   - CX-O Frontend:   http://127.0.0.1:3000
echo.
echo Press any key to close this window (services will continue running)
echo ========================================
pause > nul
