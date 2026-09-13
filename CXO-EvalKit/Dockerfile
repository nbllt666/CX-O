# CXO-EvalKit 生产镜像（LLM 评测框架，自包含子项目，不依赖父目录任何代码）。
#
# 端口与入口以实码为准：
#   - evalkit/api.py：uvicorn evalkit.api:app --host 0.0.0.0 --port 8300
#   - docker-compose.yml：ports "${CXO_EVALKIT_PORT:-8320}:8300"，healthcheck 走
#     python urllib 探活 /api/v1/health（slim 镜像不装 curl，与 CXO-Tuner 的 curl 方案区分）
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖以利用层缓存（依赖清单即 CXO-EvalKit/requirements.txt）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝 evalkit 包（服务代码）
COPY evalkit /app/evalkit

# 预建数据目录（compose 以卷覆盖：./data/evalkit → /app/data）
RUN mkdir -p /app/data

EXPOSE 8300

CMD ["uvicorn", "evalkit.api:app", "--host", "0.0.0.0", "--port", "8300"]
