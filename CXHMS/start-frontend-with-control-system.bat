@echo off
chcp 437 >nul
cls
title CXHMS - Frontend with Control Service (System)

echo ==========================================
echo    CXHMS - Chenxi Humanized Memory System
echo    Frontend + Control Service (System)
echo ==========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [INFO] Checking Python...

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found or not in PATH!
    echo Please install Python 3.8 or higher.
    pause
    exit /b 1
)
echo [OK] Python found.

echo.
echo [INFO] Installing Python dependencies...
python -m pip install -q fastapi uvicorn psutil pydantic httpx
if errorlevel 1 (
    echo [WARNING] Some dependencies may have failed to install.
)

echo.
echo [1/4] Starting Control Service in new window...
echo    - URL: http://localhost:8765

start "CXHMS Control Service" cmd.exe /c "cd /d %SCRIPT_DIR% && python backend\control_service.py"

echo [OK] Control Service starting...

timeout /t 3 /nobreak >nul

echo.
echo [2/3] Checking frontend dependencies...
cd frontend
if not exist "node_modules" (
    echo [INFO] Installing frontend dependencies...
    call npm install
    if errorlevel 1 (
        echo [ERROR] Failed to install frontend dependencies!
        pause
        exit /b 1
    )
    echo [OK] Dependencies installed.
) else (
    echo [OK] Dependencies exist.
)

echo.
echo [3/3] Checking concurrently...
call npm list concurrently >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing concurrently...
    call npm install -D concurrently >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to install concurrently!
        pause
        exit /b 1
    )
)
echo [OK] Concurrently ready.

echo.
echo ==========================================
echo    Starting Frontend...
echo ==========================================
echo    - Frontend: http://localhost:5173
echo    - Control API: http://localhost:8765
echo.
echo Press Ctrl+C to stop frontend.
echo.

call npm run dev

echo.
cd ..
pause
