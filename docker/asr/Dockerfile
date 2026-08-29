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

# 先安装 CUDA torch/torchaudio（2026-08-18 ASR GPU 加速：原 CPU wheel 使 SenseVoice
# 永远 CPU 推理、T2=280ms。改用 cu124 wheel 以启用 GPU 推理；驱动 610.88 兼容。
# 容器挂 GPU1（见 compose ASR_GPU_ID=1），SenseVoice ~230MB 模型 GPU 推理峰值 ~1GB，GPU1 空闲 9.7GB 足够）
RUN pip install --no-cache-dir \
    torch==2.4.1 torchaudio==2.4.1 \
    --index-url https://download.pytorch.org/whl/cu124

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

# 复制 ASR 容器引擎包（流式分句 + 并行识别/声纹 + 在线聚类）
COPY asr_container/ /app/asr_container/

# 复制 API 服务到 /app 根目录
COPY api_server.py /app/api_server.py

# 模型缓存（2026-08-29 修复）：原 COPY modelscope_cache/ 层已删除——
# CX-O-SERVER/modelscope_cache/ 不存在导致源码构建必失败，且 compose 已把
# asr-models 命名卷挂载到 /root/.cache/modelscope（卷非空时镜像层内容会被遮蔽）。
# 运行时模型由 compose 的 asr-models 命名卷挂载 /root/.cache/modelscope 提供；
# 如需烘焙进镜像请恢复此层并预置 CX-O-SERVER/modelscope_cache/。

# 声纹 profiles 目录（默认空池；对接 CX-O 时由宿主机 bind-mount 覆盖）
RUN mkdir -p /app/data/voiceprint \
    && printf '{\n  "version": 1,\n  "profiles": []\n}\n' > /app/data/voiceprint/speaker_profiles.json

# 让 /app 加入 sys.path，使 `from sensevoice.model import` 在容器内可解析
ENV PYTHONPATH=/app

# 端口
EXPOSE 8005

# 本体 HEALTHCHECK（补齐，与 docker/asr/docker-compose.yml 及根 docker-compose.yml
# 口径一致：容器内端口 8005 / interval 30s / timeout 10s / retries 5 / start_period 120s）
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD curl -f http://localhost:8005/health || exit 1

# 启动服务
CMD ["python", "/app/api_server.py"]