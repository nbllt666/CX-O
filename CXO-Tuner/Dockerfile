# CXO-Tuner 生产镜像（C5：2026-08-30 新建，此前 docker-compose 的 cxo-tuner 服务
# 引用 cxo/tuner:latest 但无构建源）。
#
# 端口与入口以实码为准（2026-09-05 起：宿主侧默认映射 8310，容器内仍 8300，与 CXO-ModelStation 宿主端口 8300 错开）：
#   - tuner/main.py 文档：uvicorn tuner.main:app --host 0.0.0.0 --port 8310（裸机）
#   - docker-compose.yml：ports "${CXO_TUNER_PORT:-8310}:8300"，healthcheck /api/v1/health（APIRouter prefix="/api/v1"）
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# curl：docker-compose.yml 的 healthcheck 使用 CMD curl 探活 /api/v1/health
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖以利用层缓存（依赖清单即 CXO-Tuner/requirements.txt；
# 训练重依赖 torch/unsloth/trl 由 QLoRATrainer 懒加载按需自装，不进基础镜像）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝 tuner 包（服务代码）
COPY tuner /app/tuner

# 预建数据/产出目录（compose 以卷覆盖：/app/data/dataset、/app/models/lora、/app/data/anchors）
RUN mkdir -p /app/data/dataset /app/data/lora /app/data/anchors /app/models/lora

EXPOSE 8300

CMD ["uvicorn", "tuner.main:app", "--host", "0.0.0.0", "--port", "8300"]
