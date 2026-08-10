# ============================================================
# Orpheus TTS FastAPI Bridge Dockerfile
# 复用 vllm/vllm-openai 镜像（已含 Python + PyTorch + CUDA）
# ============================================================

FROM vllm/vllm-openai:latest

WORKDIR /app

# 安装额外依赖（FastAPI + httpx + snac；PyTorch 已在基础镜像中）
RUN pip install --no-cache-dir \
    fastapi>=0.110.0 \
    uvicorn[standard]>=0.29.0 \
    pydantic>=2.6.0 \
    httpx>=0.27.0 \
    snac>=1.2.0 \
    numpy>=1.24.0

# 复制应用代码
COPY api_server.py .

# 暴露 TTS HTTP 端口
EXPOSE 5060

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:5060/health || exit 1

# 启动 FastAPI 服务（覆盖 vllm 镜像的 ENTRYPOINT）
ENTRYPOINT []
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "5060", "--workers", "1"]
