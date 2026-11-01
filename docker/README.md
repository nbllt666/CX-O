# Docker 部署索引（分服务 compose）

> change-id: `organize-per-service-docker-deploy`（2026-11-01）
> 本文件是容器化资产的唯一部署入口：每个在役服务一份 compose，可独立构建、独立启动、独立停止。

## 一、目标与编排语义

1. **每服务一份 compose**：服务定义只存在于 `docker/compose/docker-compose.<service>.yml`，镜像定义只存在于各服务目录（或 `docker/asr`、`docker/llm`）。
2. **根 `docker-compose.yml` 是兼容聚合器**：只含 `name: cxo` + `include` 引用 asr / llm / tuner / evalkit 四份推理 compose，不含任何 service 定义。因此：
   - 在仓库根执行 `docker compose up` 仍然**只启动 `asr-sensevoice`**（与拆分前一致）；
   - `docker compose --profile llm up llm`、`--profile tuner up cxo-tuner`、`--profile eval up cxo-evalkit` 语义不变；
   - `cxo-server` / `cxo-vws` / `cxo-neko-adapter` **不在**根聚合器内，需用各自独立 compose 启动。

## 二、服务一览

| 服务 | compose 文件 | 镜像定义 | 宿主端口 → 容器端口 | 关键卷 | 启动命令（仓库根执行） |
|------|-------------|---------|--------------------|--------|----------------------|
| `cxo-server`（CX-O-SERVER，FastAPI 后端） | `docker/compose/docker-compose.server.yml` | `CX-O-SERVER/Dockerfile` | `${CXO_SERVER_PORT:-8000}` → 8000 | `CX-O-SERVER/data`、`CX-O-SERVER/logs` | `docker compose -f docker/compose/docker-compose.server.yml up -d` |
| `cxo-vws`（CX-O-VoiceWorkStation，作曲/翻唱 CXFC） | `docker/compose/docker-compose.voiceworkstation.yml` | `CX-O-VoiceWorkStation/Dockerfile` | `${CXO_VWS_PORT:-8200}` → 8200 | `CX-O-VoiceWorkStation/data` | `docker compose -f docker/compose/docker-compose.voiceworkstation.yml up -d` |
| `cxo-neko-adapter`（CXO-NekoAdapter，控制面 + CXFC 桥） | `docker/compose/docker-compose.neko-adapter.yml` | `CXO-NekoAdapter/Dockerfile` | 48920 → 48920；28443-28452 → 28443-28452 | `CXO-NekoAdapter/data` | `docker compose -f docker/compose/docker-compose.neko-adapter.yml up -d` |
| `cxo-tuner`（CXO-Tuner，自我进化，profile `tuner`） | `docker/compose/docker-compose.tuner.yml` | `CXO-Tuner/Dockerfile`（既有） | `${CXO_TUNER_PORT:-8310}` → 8300 | `data/tuner_dataset`、`models/lora`、`config/character_cards` | `docker compose -f docker/compose/docker-compose.tuner.yml --profile tuner up -d` |
| `cxo-evalkit`（CXO-EvalKit，评测，profile `eval`） | `docker/compose/docker-compose.evalkit.yml` | `CXO-EvalKit/Dockerfile`（既有） | `${CXO_EVALKIT_PORT:-8320}` → 8300 | `data/evalkit`、`CXO-EvalKit/config.json`（只读） | `docker compose -f docker/compose/docker-compose.evalkit.yml --profile eval up -d` |
| `asr-sensevoice`（FunASR + SenseVoice 语音识别） | `docker/compose/docker-compose.asr.yml` | `docker/asr/Dockerfile`（既有；构建上下文 `CX-O-SERVER/`） | `${ASR_PORT:-8005}` → 8005 | `CX-O-SERVER/sensevoice`、`api_server.py`、`asr_container`、`data/voiceprint`（只读）+ 命名卷 `cxo_asr-models` | `docker compose -f docker/compose/docker-compose.asr.yml up -d` |
| `llm`（vLLM / TRT-LLM 对话大模型，profile `llm`） | `docker/compose/docker-compose.llm.yml` | `docker/llm/Dockerfile.${LLM_BACKEND:-vllm}`（既有） | `${LLM_PORT:-8080}` → 8080 | `${LLM_MODELS_DIR:-../../models}`（只读）+ 命名卷 `cxo_llm-engines` | `docker compose -f docker/compose/docker-compose.llm.yml --profile llm up -d` |

Weaviate 向量库变体（5 份，官方镜像，变体文件内各自声明）：

| 变体 | compose 文件 | 用途 | 宿主端口 → 容器端口 | 卷 |
|------|-------------|------|--------------------|----|
| CPU | `docker/compose/weaviate/cpu.yml` | Weaviate + CPU t2v-transformers（distiluse 多语） | 8090 → 8080；50061 → 50051 | `weaviate_data`、`transformers_cache` |
| GPU | `docker/compose/weaviate/gpu.yml` | 仅 Weaviate，向量化交给外部 | 8090 → 8080；50061 → 50051 | `weaviate_data` |
| GPU 自定义 | `docker/compose/weaviate/gpu-custom.yml` | 自带 `weaviate-embeddings-gpu:latest` 镜像 | 8090 → 8080；50061 → 50051 | `weaviate_data` |
| GPU 全量 | `docker/compose/weaviate/gpu-full.yml` | MiniLM-L6-v2 transformers-inference（额外映射 8081 → 8080） | 8090 → 8080；50061 → 50051；8081 → 8080 | `weaviate_data` |
| GPU 多语 | `docker/compose/weaviate/gpu-multilingual.yml` | paraphrase-multilingual-mpnet-base-v2 | 8090 → 8080；50061 → 50051 | `weaviate_data` |

## 三、常用命令

```bash
# 单服务启动 / 停止 / 查看日志
docker compose -f docker/compose/docker-compose.server.yml up -d
docker compose -f docker/compose/docker-compose.server.yml down
docker compose -f docker/compose/docker-compose.server.yml logs -f

# 带 profile 的服务（tuner / evalkit / llm）
docker compose -f docker/compose/docker-compose.tuner.yml --profile tuner up -d
docker compose -f docker/compose/docker-compose.evalkit.yml --profile eval up -d
docker compose -f docker/compose/docker-compose.llm.yml --profile llm up -d

# 根聚合器（行为与拆分前一致：裸 up 仅 asr-sensevoice）
docker compose up -d
docker compose --profile llm up llm
docker compose --profile tuner up cxo-tuner
docker compose --profile eval up cxo-evalkit

# Weaviate 变体（按需选一份）
docker compose -f docker/compose/weaviate/cpu.yml up -d

# 语法 / 路径校验（不启动容器）
docker compose -f docker/compose/docker-compose.server.yml config
docker compose -f docker/compose/weaviate/cpu.yml config
docker compose config                       # 根聚合器
docker compose --profile tuner config --services
```

## 四、共享资源

- **网络**：所有服务 compose 显式固定网络名 `cxo-inference`（`name: cxo-inference`），因此**无论用独立 `-f` 还是根聚合器启动，容器都落在同一个网络**，容器内可按服务名互联：`http://cxo-server:8000`、`http://asr-sensevoice:8005`、`http://llm:8080`。
  - 例外：Weaviate 变体沿用其自有的 `weaviate-network`，不加入 `cxo-inference`。
- **命名卷**（同样显式固定，独立 `-f` 与根聚合器共用同一卷，不会出现 `compose_*` / `cxo_*` 分裂）：
  - `cxo_asr-models`：ASR 的 modelscope 模型缓存。
  - `cxo_llm-engines`：LLM 引擎目录（TRT-LLM 等）。
- 注意：`cxo_asr-models` 非空时 Docker 会跳过「镜像内模型 → 空卷」初始化复制；更换镜像内模型后需 `docker volume rm cxo_asr-models` 重建空卷。

## 五、环境变量

- 根 `.env.example` 的「分服务 Docker 部署（docker/compose/）」段给出 `CXO_SERVER_PORT` / `CXO_VWS_PORT` / `CXO_VWS_CORS_ORIGINS`；各 compose 通过 `env_file: ../../.env`（`required: false`）加载，缺失 `./.env` 时不影响独立启动。
- `ADMIN_API_KEY`（必填）：管理端点、记忆端点与 WebSocket 握手的统一密钥；容器部署同样需要注入，且前端与 `CXO-EvalKit/config.json` 的 `target.admin_api_key` 必须一致。
- `LLM_MODELS_DIR`：LLM 模型目录挂载源，默认 `../../models`（相对 compose 文件位置，即仓库根 `models/`）。
- Neko 专用变量（compose 内已写定，容器环境不可省略）：`CXO_NEKO_ADAPTER_CONTROL_HOST=0.0.0.0`、`CXO_NEKO_ADAPTER_BRIDGE_HOST=0.0.0.0`、`CXO_NEKO_ADAPTER_BRIDGE_PUBLIC_HOST=cxo-neko-adapter`、`CXO_NEKO_ADAPTER_BACKEND_URL=http://cxo-server:8000`。其中「监听地址」与「对外通告地址」不可混用：`*_HOST` 只决定监听，`BRIDGE_PUBLIC_HOST` 是注册给后端的可达主机名。

## 六、已知边界（不做 / 待恢复）

| 项 | 边界说明 | 依据 |
|----|---------|------|
| APP-Frontend | **不容器化**，维持 Electron / 本地 dev 形态（浏览器模式 `http://localhost:3100`） | 人类裁决 D-4 |
| CXO-ModelStation | 当前工作区**目录缺失**，未生成任何 Dockerfile / compose；登记为**阻塞待目录恢复后补齐** | spec Non-goals；本索引不含其镜像 |
| CX-O-VoiceWorkStation | 镜像内不含分离引擎（`engines/demucs`、`AudioSep`）与 DiffSinger；SoundFont（`.sf2`）需外部挂载并让 `music.soundfont_path` 指向容器内路径。镜像已装 `ffmpeg` / `fluidsynth` | Task 3 边界 |
| CXO-NekoAdapter | 镜像只提供 `node` + `python3`；neko 插件服务器的第三方 Python 依赖不在镜像内，完整插件能力需外部挂载/安装。缺失时控制面仍可用 | Task 4 边界 |
| CXO-NekoAdapter TLS | 自签证书 SAN 仅覆盖 `127.0.0.1`；若后端对桥主机名做证书校验，需重建包含 `cxo-neko-adapter` 的证书 | Task 4 边界 |
| 构建忽略 | `docker/asr` 的 ASR 白名单走 `docker/asr/Dockerfile.dockerignore`，需 BuildKit（Docker 23+ 默认开启）；`CX-O-SERVER/.dockerignore` 为 SERVER 黑名单，两者互不干扰 | Task 2 |
| 模块级 AGENTS 陈旧命令 | `CXO-EvalKit/AGENTS.md:30` 仍写 `docker compose --profile eval up cxo-evalkit`；该命令经根聚合器仍兼容有效，但按 rules-4 模块级 AGENTS 禁止手动修改，故保留并在本索引登记 | rules-4；GN-004 O-5 |
| 裸机链路 | `start-all.bat` / `stop-all.bat` 未改动，仍是一键裸机入口；容器化为可选路径 | spec Non-goals |
