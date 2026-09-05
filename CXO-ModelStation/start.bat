@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM ============================================
REM CXO-ModelStation 启动脚本
REM 用法:
REM   start.bat        仅启动后端(端口 8300)
REM   start.bat dev    后端(新窗口) + 前端 dev(3300)
REM ============================================
REM 部署约束与目录说明:
REM 1. 单 worker 部署: 训练状态为进程内缓存,
REM    禁止以多 worker / reload 模式启动后端
REM 2. 训练数据与模型位于本目录 data/ 下
REM    (data/training/sovits_svc 与 data/models/sovits_svc)
REM 3. 前端 dev 端口 3300, /api 代理到 127.0.0.1:8300
REM 4. 生产模式: frontend/ 执行 npm run build 后,
REM    产物 dist/ 由后端自动静态托管(无需单独启动前端)
REM ============================================

REM 解释器选择: 优先项目根 py311 虚拟环境, 缺失时回退全局 python
set "PYTHON_EXE="
if exist "%~dp0..\py311\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\py311\Scripts\python.exe"
    echo [信息] 使用项目虚拟环境 ..\py311
) else (
    echo [警告] 未找到 ..\py311\Scripts\python.exe, 回退使用全局 python
    python --version > nul 2>&1
    if errorlevel 1 (
        echo [错误] 未找到 Python, 请安装 Python 或先在项目根目录运行 create-env.bat
        pause
        exit /b 1
    )
    set "PYTHON_EXE=python"
)

if /i "%~1"=="dev" goto :dev
if /i "%~1"=="frontend" goto :dev

REM 引擎目录存在性检查（自包含化 2026-09-05：引擎位于本目录 engines/ 下）
if not exist "%~dp0engines\" (
    echo [错误] 未找到引擎目录 %~dp0engines
    echo [提示] 引擎缺失会导致训练/语料生成不可用，请运行: python tools\setup_engines.py --clone-melotts
    echo [提示] 详见 DEPLOY.md 第 3 节「三引擎就位」
    pause
    exit /b 1
)

echo ============================================
echo 启动 CXO-ModelStation 后端 (http://127.0.0.1:8300)
echo 单 worker: 训练状态进程内缓存, 勿改多 worker
echo ============================================
%PYTHON_EXE% -m modelstation.main
pause
goto :eof

:dev
echo [信息] dev 模式: 新窗口启动后端 8300, 本窗口启动前端 dev 3300
start "CXO-ModelStation-Backend" cmd /c "%~f0"
echo [等待后端窗口拉起...]
ping -n 2 127.0.0.1 > nul 2>&1

where npm > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 npm, 无法启动前端 dev, 请先安装 Node.js 18+
    pause
    exit /b 1
)

cd /d "%~dp0frontend"
echo 启动前端 dev (http://localhost:3300, /api 已代理到 8300)...
call npm run dev
cd /d "%~dp0"
pause
