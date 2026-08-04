# ASR SenseVoice Dockerfile
# 基于 FunASR 提供 SenseVoice 语音识别服务

FROM python:3.11-slim

WORKDIR /app

# 使用国内镜像源加速
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 先安装 CPU-only torch/torchaudio（使用 2.4+ 版本以兼容 transformers）
RUN pip install --no-cache-dir \
    torch==2.4.1 torchaudio==2.4.1 \
    --index-url https://download.pytorch.org/whl/cpu

# 安装其余 Python 依赖（降级 numpy 到 < 2.0 以兼容旧模块）
RUN pip install --no-cache-dir \
    funasr \
    modelscope \
    fastapi \
    uvicorn \
    "numpy<2.0" \
    httpx \
    pydantic \
    kaldi-native-fbank \
    onnxruntime \
    python-multipart \
    websockets

# 复制 SenseVoice 模型代码
COPY sensevoice/ /app/sensevoice/

# 复制 utils 目录（model.py 依赖 utils.ctc_alignment）
COPY sensevoice/utils/ /app/utils/

# 复制 API 服务到 /app 根目录
COPY api_server.py /app/api_server.py

# 让 /app 加入 sys.path，使 `from sensevoice.model import` 在容器内可解析
ENV PYTHONPATH=/app

# 端口
EXPOSE 8005

# 启动服务
CMD ["python", "/app/api_server.py"]