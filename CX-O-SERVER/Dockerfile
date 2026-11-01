# CX-O-SERVER Dockerfile
# change-id: organize-per-service-docker-deploy（2026-11-01）
#
# 构建上下文 = 本目录（CX-O-SERVER/）：
#   docker build -f CX-O-SERVER/Dockerfile CX-O-SERVER
#   或 docker compose -f docker/compose/docker-compose.server.yml up -d
#
# 依赖清单来源：本目录 requirements.txt（自包含，2026-11-01 由根 requirements.txt
#   迁入；根目录仅保留 `-r CX-O-SERVER/requirements.txt` 兼容垫片）。
#
# 上下文裁剪：本目录 .dockerignore 为 SERVER 黑名单（排除 data/ logs/ tests/
#   backups/ config.json 等）；ASR 构建白名单已迁到 docker/asr/Dockerfile.dockerignore。
#
# config.json 不入镜像：API Key 等密钥不允许烘入镜像层，运行时通过环境变量
#   （env_file / environment）注入，或按需用只读 bind mount 挂载
#   （../../CX-O-SERVER/config.json:/app/config.json:ro，不默认启用）。
#
# 注意：镜像不含 sensevoice/ 与 asr_container/（ASR 专用），SERVER 以 remote 模式
#   调用独立 ASR 容器；embedded 模式加载失败时服务内置的降级逻辑会切到 remote。

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

# 系统依赖：curl（HEALTHCHECK 探针）、ffmpeg / libsndfile1（音频解码与读写）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖再拷代码：最大化层缓存复用
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY server /app/server

# 运行时可写目录（compose 以 bind mount 覆盖）
RUN mkdir -p /app/data /app/logs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=120s \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn","server.main:app","--host","0.0.0.0","--port","8000"]
