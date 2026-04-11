@echo off
chcp 65001 > nul
setlocal

echo ========================================
echo 启动 vLLM (Docker) - GLM-4V GGUF Q8
echo ========================================

set "GGUF_PATH=C:\CX-O\CX-O\models\glm-4v-9b-Q8_0.gguf"
set "PORT=8000"

echo.
echo GGUF 模型： %GGUF_PATH%
echo 端口： %PORT%
echo.
echo 注意：首次启动会下载 tokenizer，请耐心等待
echo.

if not exist "%GGUF_PATH%" (
    echo [错误] GGUF 模型文件不存在！
    echo 请先下载 glm-4v-9b-Q8_0.gguf 到 models 目录
    pause
    exit /b 1
)

echo 启动 vLLM 服务...
docker compose -f vllm-docker-compose.yml up -d

echo.
echo vLLM 服务已启动
echo 访问地址：http://localhost:%PORT%
echo API 文档：http://localhost:%PORT%/docs
echo.
pause
