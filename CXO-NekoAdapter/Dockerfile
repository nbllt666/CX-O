# CXO-NekoAdapter 镜像（多阶段）
# change-id: organize-per-service-docker-deploy（2026-11-01）
#
# 镜像边界说明（重要）：
#   - 镜像只提供 Node.js 20 + python3 解释器本身；neko 插件服务器所需的第三方
#     Python 依赖（config/plugin/utils 等运行期包）不在镜像内，需通过外部挂载
#     neko 源码目录 + 在容器内/宿主侧安装依赖，或使用自带完整环境的外部镜像；
#     缺失时容器仍可拉起控制面（/health、/config 等 API 可用）。
#   - 控制面 / CXFC 桥的监听地址由配置 controlHost / bridgeHost 决定，可经环境变量
#     CXO_NEKO_ADAPTER_CONTROL_HOST / CXO_NEKO_ADAPTER_BRIDGE_HOST 覆盖；镜像默认
#     保持本机安全语义（未设置环境变量时仅绑定 127.0.0.1，容器内需由 compose 设为 0.0.0.0）。
#   - 数据目录由 CXO_NEKO_ADAPTER_DATA_DIR 指向 /app/data（config.json / certs 持久化）。
#
# 构建: docker build -f CXO-NekoAdapter/Dockerfile -t cxo/neko-adapter:latest CXO-NekoAdapter

# ── 阶段 1：编译 TypeScript ────────────────────────────────────────────────
FROM node:20-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# ── 阶段 2：运行镜像 ───────────────────────────────────────────────────────
FROM node:20-bookworm-slim AS runtime
ENV NODE_ENV=production \
    CXO_NEKO_ADAPTER_DATA_DIR=/app/data

# python3 供 neko 插件服务器 sidecar 使用（第三方 Python 依赖仍需外部提供，见文件头）
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package.json package-lock.json ./
# 运行期依赖（node-forge 生成 HTTPS 桥证书），不安装 devDependencies
RUN npm ci --omit=dev

COPY --from=build /src/dist ./dist
RUN mkdir -p /app/data

# 控制面 48920；CXFC 桥冲突递增段 28443-28452（与 MAX_BRIDGE_ATTEMPTS=10 对齐）
EXPOSE 48920 28443-28452

# 探活控制面 /health（容器内由 0.0.0.0 监听，127.0.0.1 可达）
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:48920/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "dist/index.js"]
