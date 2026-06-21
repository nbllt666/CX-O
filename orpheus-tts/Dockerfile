# ============================================================
# Orpheus TTS FastAPI Bridge Dockerfile
# 轻量级镜像：Python 3.11 + CUDA + SNAC 解码器
# ============================================================

FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

# 避免 tzdata 交互提示
ENV DEBIAN_FRONTEND=noninteractive

# 安装系统依赖 + Python 3.11
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    python3.11-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

WORKDIR /app

# 安装 Python 依赖（先复制 requirements.txt 利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY api_server.py .

# 暴露 TTS HTTP 端口
EXPOSE 5060

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:5060/health || exit 1

# 启动 FastAPI 服务
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "5060", "--workers", "1"]
