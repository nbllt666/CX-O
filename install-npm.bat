@echo off
chcp 65001 > nul
title CX-O Install npm Dependencies

echo ========================================
echo CX-O Microservices - Install npm Dependencies
echo ========================================

set "ROOT_DIR=%~dp0"

echo.
echo Checking Node.js and npm...
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found, please install Node.js first
    echo Download: https://nodejs.org/
    pause
    exit /b 1
)

node --version
npm --version

echo.
echo ========================================
echo Installing cx-o-frontend dependencies
echo ========================================

if not exist "%ROOT_DIR%cx-o-frontend" (
    echo ERROR: Frontend directory not found: %ROOT_DIR%cx-o-frontend
    pause
    exit /b 1
)

pushd "%ROOT_DIR%cx-o-frontend"

if exist "node_modules" (
    echo node_modules exists, skipping installation
) else (
    echo Installing dependencies...
    npm install --registry=https://registry.npmmirror.com
)

if %errorlevel% neq 0 (
    echo.
    echo Installation failed, trying official source...
    npm install
)

popd

echo.
echo ========================================
echo npm dependencies installed!
echo ========================================
pause
