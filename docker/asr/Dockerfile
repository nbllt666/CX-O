# ASR SenseVoice Dockerfile
# 基于 FunASR 提供 SenseVoice 语音识别服务

FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install --no-cache-dir \
    funasr \
    modelscope \
    torch \
    torchaudio \
    fastapi \
    uvicorn \
    numpy \
    httpx \
    pydantic

# 复制 SenseVoice 模型代码和 API 服务
COPY sensevoice/ /app/sensevoice/

# 端口
EXPOSE 8005

# 启动服务
CMD ["python", "/app/sensevoice/api_server.py"]