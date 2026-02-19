@echo off
chcp 936 >nul
cls
title CXHMS - Fix Environment

echo ==========================================
echo    CXHMS - Fix Environment Variables
echo ==========================================
echo.

echo [INFO] Checking environment variables...

REM Clean potentially problematic environment variables
set XY=
set OXY=
set xy=
set oxy=
set MAX_THREADS=
set S=
set ONDA_PATH=
set f=
set or=
set ase=

echo [OK] Environment variables cleaned.
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

echo [INFO] Current directory: %CD%
echo.

if exist "%SCRIPT_DIR%Miniconda3\Scripts\activate.bat" (
    echo [OK] Found local Conda: %SCRIPT_DIR%Miniconda3
    set "CONDA_PATH=%SCRIPT_DIR%Miniconda3"
) else (
    echo [WARN] Local Conda not found, trying system Conda...
    where conda >nul 2>&1
    if %errorlevel% == 0 (
        echo [OK] Found system Conda
    ) else (
        echo [WARN] Conda not found, please install Conda first
    )
)

echo.
echo ==========================================
echo [OK] Fix complete!
echo ==========================================
echo.
echo Please run CXHMS using:
echo   - Double click: 1.1.启动前端(含控制服务)(Conda).bat
echo   - Or: 1.2.启动前端(含控制服务)(系统).bat
echo.

cmd /k
