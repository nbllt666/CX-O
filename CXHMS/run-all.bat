@echo off
chcp 437 >nul
cls
title CXHMS - All Services

echo ==========================================
echo    CXHMS - Chenxi Humanized Memory System
echo ==========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [INFO] Starting Control Service...
start "CXHMS Control Service" cmd.exe /c "%SCRIPT_DIR%Miniconda3\Scripts\activate.bat base && cd /d %SCRIPT_DIR% && python backend\control_service.py"
echo [OK] Control Service starting on http://localhost:8765

echo.
echo [INFO] Starting Frontend...
cd frontend
call npm run dev
