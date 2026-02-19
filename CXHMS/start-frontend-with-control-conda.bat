@echo off
chcp 437 >nul
cls
title CXHMS - Frontend with Control Service (Conda)

echo ==========================================
echo    CXHMS - Chenxi Humanized Memory System
echo    Frontend + Control Service (Conda)
echo ==========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [INFO] Checking Conda environment...

set "CONDA_PATH=%SCRIPT_DIR%Miniconda3"
if not exist "%CONDA_PATH%\Scripts\activate.bat" (
    echo [ERROR] Conda not found!
    echo Please use system Python version instead.
    pause
    exit /b 1
)

echo [OK] Conda path found.

echo.
echo [1/4] Starting Control Service in new window...
echo    - URL: http://localhost:8765

:: 使用 base 环境启动控制服务
start "CXHMS Control Service" cmd.exe /c "cd /d %SCRIPT_DIR% && %CONDA_PATH%\Scripts\activate.bat base && python backend\control_service.py"

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
