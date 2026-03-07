@echo off
chcp 65001 >nul
echo ========================================
echo     CX-O 一键清理脚本
echo     清理所有记忆与配置
echo ========================================
echo.
echo 警告：此操作将删除以下内容：
echo   - 记忆数据库 (memories.db)
echo   - 会话数据库 (sessions.db)
echo   - CXHMS 数据库 (cxhms.db)
echo   - ACP 配置 (agents.yaml, connections.yaml, groups.yaml)
echo   - 所有运行时生成的数据
echo.
echo 不会删除的：
echo   - 配置文件 (agents.json)
echo   - 代码文件
echo.
echo 正在停止服务...
echo.

:: 停止可能正在运行的服务
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *CXHMS*" 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *Gateway*" 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *SenseVoice*" 2>nul

echo 正在清理数据库文件...
echo.

:: 清理 CXHMS/data 目录下的数据库文件
if exist "CXHMS\data\memories.db" (
    del /F "CXHMS\data\memories.db"
    echo 已删除: CXHMS\data\memories.db
)

if exist "CXHMS\data\memories.db-shm" (
    del /F "CXHMS\data\memories.db-shm"
    echo 已删除: CXHMS\data\memories.db-shm
)

if exist "CXHMS\data\memories.db-wal" (
    del /F "CXHMS\data\memories.db-wal"
    echo 已删除: CXHMS\data\memories.db-wal
)

if exist "CXHMS\data\sessions.db" (
    del /F "CXHMS\data\sessions.db"
    echo 已删除: CXHMS\data\sessions.db
)

if exist "CXHMS\data\cxhms.db" (
    del /F "CXHMS\data\cxhms.db"
    echo 已删除: CXHMS\data\cxhms.db
)

echo.
echo 正在清理 ACP 配置...
echo.

:: 清理 ACP 配置
if exist "CXHMS\data\acp\agents.yaml" (
    del /F "CXHMS\data\acp\agents.yaml"
    echo 已删除: CXHMS\data\acp\agents.yaml
)

if exist "CXHMS\data\acp\connections.yaml" (
    del /F "CXHMS\data\acp\connections.yaml"
    echo 已删除: CXHMS\data\acp\connections.yaml
)

if exist "CXHMS\data\acp\groups.yaml" (
    del /F "CXHMS\data\acp\groups.yaml"
    echo 已删除: CXHMS\data\acp\groups.yaml
)

echo.
echo ========================================
echo 清理完成！
echo ========================================
echo.
echo 下次启动服务时将自动创建新的数据库
echo.
pause
