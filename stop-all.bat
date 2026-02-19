@echo off
chcp 65001 > nul
title CX-O Stop All Services

echo ========================================
echo CX-O Microservices - Stop All Services
echo ========================================

echo Stopping all Python services...
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul

echo Stopping all Node.js services...
taskkill /f /im node.exe 2>nul

echo.
echo ========================================
echo All services stopped
echo ========================================
pause
