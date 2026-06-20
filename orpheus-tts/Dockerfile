# ============================================================
# Orpheus TTS FastAPI Bridge Dockerfile
# 基于 PyTorch CUDA 镜像，内置 SNAC 解码器
# ============================================================

FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
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
