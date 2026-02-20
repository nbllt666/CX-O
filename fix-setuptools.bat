@echo off
chcp 65001 > nul

echo ========================================
echo Fixing setuptools...
echo ========================================

cd /d %~dp0

rd /s /q "Miniconda3\lib\site-packages\setuptools" 2>nul
rd /s /q "Miniconda3\lib\site-packages\setuptools-75.8.0.dist-info" 2>nul
rd /s /q "Miniconda3\lib\site-packages\setuptools-82.0.0.dist-info" 2>nul
rd /s /q "Miniconda3\lib\site-packages\pkg_resources" 2>nul

Miniconda3\python.exe -m pip install setuptools wheel --no-cache-dir

echo ========================================
echo Done!
echo ========================================
pause
