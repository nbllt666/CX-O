@echo off
chcp 65001 > nul
title CX-O Install All Dependencies

echo ========================================
echo CX-O Microservices - Install All Dependencies
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

REM ========================================
REM Install Python Dependencies
REM ========================================
echo ========================================
echo [1/2] Installing Python Dependencies
echo ========================================

if exist "%ROOT_DIR%requirements.txt" (
    echo Installing from Tsinghua mirror...
    "%PYTHON_EXE%" -m pip install -r "%ROOT_DIR%requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout=100
    
    if %errorlevel% neq 0 (
        echo.
        echo Some dependencies failed, trying official source...
        "%PYTHON_EXE%" -m pip install -r "%ROOT_DIR%requirements.txt" -i https://pypi.org/simple --timeout=100
    )
) else (
    echo requirements.txt not found
)

echo.
REM ========================================
REM Install npm Dependencies
REM ========================================
echo ========================================
echo [2/2] Installing npm Dependencies
echo ========================================

where node >nul 2>nul
if %errorlevel% neq 0 (
    echo WARNING: Node.js not found, skipping npm dependencies
    echo Download: https://nodejs.org/
) else (
    node --version
    npm --version
    echo.
    
    if not exist "%ROOT_DIR%cx-o-frontend" (
        echo WARNING: Frontend directory not found: %ROOT_DIR%cx-o-frontend
        echo Skipping npm dependencies
    ) else (
        pushd "%ROOT_DIR%cx-o-frontend"
        
        if exist "node_modules" (
            echo node_modules exists, skipping installation
        ) else (
            echo Installing frontend dependencies...
            echo Directory: %CD%
            echo.
            npm install --registry=https://registry.npmmirror.com
            
            if %errorlevel% neq 0 (
                echo.
                echo WARNING: npm install failed, trying official source...
                npm install
            )
        )
        
        popd
    )
)

echo.
echo ========================================
echo All dependencies installed!
echo ========================================
echo.
echo Press any key to exit...
pause > nul
