# CX-O 部署指南

本文档提供 CX-O（晨曦人格化记忆系统）的完整部署指南，涵盖系统要求、快速开始、各服务详细部署步骤、外部依赖部署、配置说明及常见问题排查。

---

## 目录

1. [系统要求](#1-系统要求)
2. [快速开始（最小化部署）](#2-快速开始最小化部署)
3. [各服务详细部署步骤](#3-各服务详细部署步骤)
4. [外部依赖部署](#4-外部依赖部署)
5. [配置说明](#5-配置说明)
6. [常见问题排查](#6-常见问题排查)

---

## 1. 系统要求

### 1.1 基础环境

| 组件 | 最低版本 | 推荐版本 | 说明 |
|------|---------|---------|------|
| Python | 3.11 | 3.11+ | 项目 `pyproject.toml` 指定 `python_version = "3.10"`，但 `requirements.txt` 和 `create-env.bat` 要求 3.11+ |
| Node.js | 18.x | 20.x LTS | 前端构建所需 |
| npm | 9.x | 10.x | 随 Node.js 安装 |
| Git | 2.30+ | 最新 | 代码拉取 |

### 1.2 GPU 要求

| 场景 | GPU 要求 | 说明 |
|------|---------|------|
| 仅对话（无本地 ASR/TTS） | 无需 GPU | 使用远程 ASR/TTS 服务 |
| 本地 ASR（SenseVoice） | NVIDIA GPU, 4GB+ VRAM | CUDA 12.1+ |
| 本地 TTS（F5-TTS） | NVIDIA GPU, 8GB+ VRAM | CUDA 12.1+ |
| CosyVoice 语音合成 | NVIDIA GPU, 8GB+ VRAM | CUDA 12.1+ |
| F5-TTS TensorRT 加速推理 | NVIDIA GPU, 16GB+ VRAM | TensorRT-LLM, CUDA 12.x |

> **提示**：无 GPU 环境可将 ASR/TTS 配置为 `mode: remote`，由远程服务提供语音能力。

### 1.3 操作系统

- **Windows 10/11**（主要支持平台，项目提供 `.bat` 启动脚本）
- **Linux**（Docker 部署推荐，部分组件如 deepspeed 仅支持 Linux）

### 1.4 磁盘空间

| 组件 | 预估空间 |
|------|---------|
| 代码仓库 | ~2 GB |
| Python 依赖 | ~5 GB |
| Node.js 依赖 | ~500 MB |
| LLM 模型（Ollama） | 4~20 GB（视模型大小） |
| ASR 模型（SenseVoiceSmall） | ~1 GB |
| TTS 模型（F5TTS_v1_Base） | ~1.5 GB |
| CosyVoice 模型 | ~2 GB |
| Weaviate 数据 | 视使用量增长 |

**建议总磁盘空间**：50 GB 以上（含模型文件）。

---

## 2. 快速开始（最小化部署）

最小化部署仅启动核心对话功能，不包含语音和向量数据库。

### 2.1 前置条件

- Python 3.11+ 已安装
- Node.js 18+ 已安装
- [Ollama](https://ollama.com) 已安装并运行（默认端口 11434）

### 2.2 步骤

```bash
# 1. 克隆仓库
git clone <repo-url> CX-O
cd CX-O

# 2. 创建并激活 Python 虚拟环境
python -m venv py311
# Windows:
call py311\Scripts\activate.bat
# Linux:
source py311/bin/activate

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 拉取 Ollama 模型
ollama pull qwen3:latest

# 5. 启动 CX-O-SERVER
cd CX-O-SERVER
set PYTHONPATH=%CD%\..
python -m server.main
# 服务启动在 http://localhost:8000

# 6. 新终端：安装并启动前端
cd CX-O-Frontend
npm install
npm run dev
# 前端启动在 http://localhost:5173（Vite 默认端口）
```

### 2.3 一键启动（Windows）

项目提供了 `start-all.bat` 一键启动脚本，会依次启动 CX-O-SERVER（端口 8000）、CX-O-VoiceWorkStation（端口 8200）和 CX-O-Frontend（端口 3000）：

```bat
start-all.bat
```

启动完成后自动打开浏览器访问 `http://localhost:3000`。

---

## 3. 各服务详细部署步骤

### 3.1 CX-O-SERVER

CX-O-SERVER 是核心后端服务，整合了 Gateway、Backend、ASR、TTS 为单体服务。

**端口**：8000（默认）

**启动命令**：

```bash
cd CX-O-SERVER
set PYTHONPATH=%CD%\..
python -m server.main
```

或使用启动脚本：

```bat
CX-O-SERVER\start.bat
```

**主要功能模块**：

| 模块 | 说明 |
|------|------|
| API 路由 | `/api/*` — 对话、记忆、上下文、工具、ACP 等 REST API |
| WebSocket | `/ws` — 实时对话；`/ws/live` — 直播模式 |
| Gateway | WebSocket 处理器注册、Control 服务代理 |
| 记忆管理 | SQLite + Weaviate 向量搜索 |
| 上下文管理 | 会话上下文窗口与摘要 |
| LLM 客户端 | 支持 Ollama / vLLM / OpenAI / Anthropic / DeepSeek |
| ASR 服务 | SenseVoice（embedded）或远程 ASR |
| TTS 服务 | F5-TTS / CosyVoice / IndexTTS（embedded 或远程） |
| 图数据库 | SQLite 图存储 + Weaviate 语义搜索 |
| ACP 协议 | Agent 通信协议，发现/连接/群组 |
| CXFC 框架 | 插件发现与 Skill 注册 |

**健康检查**：

```bash
curl http://localhost:8000/health
```

**API 文档**：启动后访问 `http://localhost:8000/docs`（Swagger UI）或 `http://localhost:8000/redoc`。

### 3.2 CX-O-Gateway

> **注意**：Gateway 已整合进 CX-O-SERVER 单体服务中，无需单独部署。Gateway 的路由注册在 `server/gateway/server.py` 中完成，随 CX-O-SERVER 一同启动。

Gateway 负责：
- WebSocket 端点（`/ws`, `/ws/live`）
- WebSocket 统计（`/api/ws/stats`）
- Control 服务代理（`/control/{path}`）
- WebSocket 处理器注册

如需单独配置 Gateway 参数，可通过环境变量 `CXO_GATEWAY_*` 覆盖：

```bash
set CXO_GATEWAY_HOST=0.0.0.0
set CXO_GATEWAY_PORT=8100
```

### 3.3 CX-O-VoiceWorkStation

语音工作站，提供参考音频生成、F5-TTS 微调、So-VITS-SVC 训练/推理、VoxCPM 参考音频生成功能。

**端口**：8200（默认）

**启动命令**：

```bash
cd CX-O-VoiceWorkStation
set PYTHONPATH=%CD%\..
python -m workstation.main
```

或使用启动脚本：

```bat
CX-O-VoiceWorkStation\start.bat
```

**API 路由**：

| 路由前缀 | 说明 |
|----------|------|
| `/api/ref-audio` | 参考音频生成 |
| `/api/f5tts-finetune` | F5-TTS 微调 |
| `/api/sovits-svc` | So-VITS-SVC 训练/推理 |
| `/api/voxcpm` | VoxCPM 参考音频生成 |
| `/api/workflow` | 工作流编排 |

**健康检查**：

```bash
curl http://localhost:8200/health
```

**配置文件**：`CX-O-VoiceWorkStation/config.yaml`

### 3.4 CX-O-Frontend

基于 React + Vite + TypeScript 的前端应用。

**开发服务器端口**：5173（Vite 默认），`start-all.bat` 中配置为 3000

**安装与启动**：

```bash
cd CX-O-Frontend
npm install
npm run dev
```

**生产构建**：

```bash
npm run build
```

构建产物输出到 `dist/` 目录，可使用 Nginx 等静态服务器托管。

**环境变量**：复制 `.env.example` 为 `.env` 并修改：

```bash
cp .env.example .env
```

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VITE_API_URL` | `http://localhost:8100` | API 服务地址（Gateway 端口） |
| `VITE_WS_URL` | `ws://localhost:8100` | WebSocket 服务地址 |
| `VITE_CONTROL_SERVICE_URL` | `http://localhost:8765` | 控制服务地址 |
| `VITE_VOICE_WS_URL` | `http://127.0.0.1:8200` | 语音工作站服务地址 |
| `VITE_REQUEST_TIMEOUT` | `30` | 请求超时（秒） |
| `VITE_LOG_LEVEL` | `info` | 日志级别 |

---

## 4. 外部依赖部署

### 4.1 Ollama（LLM 推理）

Ollama 是默认的 LLM 推理后端，CX-O 通过 OpenAI 兼容 API 与之交互。

**安装**：

```bash
# Windows: 下载安装包
# https://ollama.com/download

# Linux:
curl -fsSL https://ollama.com/install.sh | sh
```

**启动与模型拉取**：

```bash
# 启动 Ollama 服务（默认端口 11434）
ollama serve

# 拉取推荐模型
ollama pull qwen3:latest
```

**配置**：

在 `config/default.yaml` 中修改 LLM 配置：

```yaml
models:
  main:
    provider: ollama
    host: http://localhost:11434
    model: qwen3:latest
```

或通过环境变量覆盖：

```bash
set CXO_LLM_PROVIDER=ollama
set CXO_LLM_HOST=http://localhost:11434
set CXO_LLM_MODEL=qwen3:latest
```

**支持的 LLM 提供商**：

| Provider | 配置值 | 说明 |
|----------|--------|------|
| Ollama | `ollama` | 本地推理，默认选项 |
| vLLM | `vllm` | 高性能本地推理 |
| OpenAI | `openai` | 需配置 `api_key` |
| Anthropic | `anthropic` | 需配置 `api_key` |
| DeepSeek | `deepseek` | 需配置 `api_key` |

### 4.2 Weaviate（向量数据库，可选）

Weaviate 用于记忆的向量搜索和语义检索，支持记忆去重和相似度查询。

#### 方式一：Docker Compose（推荐）

项目提供了多种 Weaviate Docker Compose 配置：

```bash
# CPU 模式（无 GPU 向量化）
docker-compose -f docker-compose.weaviate.yml up -d

# GPU 模式（含 text2vec-transformers 向量化）
docker-compose -f docker-compose.weaviate-gpu.yml up -d

# GPU + 多语言模型
docker-compose -f docker-compose.weaviate-gpu-multilingual.yml up -d

# GPU + 完整功能
docker-compose -f docker-compose.weaviate-gpu-full.yml up -d
```

**默认端口映射**：

| 端口 | 说明 |
|------|------|
| 8090 → 8080 | Weaviate REST API |
| 50061 → 50051 | Weaviate gRPC API |

> **注意**：项目默认配置的 Weaviate 端口为 `8090`（REST）和 `50061`（gRPC），与标准 Weaviate 端口不同，以避免端口冲突。

#### 方式二：Weaviate Embedded

无需 Docker，CX-O-SERVER 可内嵌启动 Weaviate：

在 `config/default.yaml` 中设置：

```yaml
memory:
  vector_backend: weaviate_embedded
  weaviate:
    embedded: true
```

> **注意**：Embedded 模式需要安装 `weaviate-client` 的 embedded 依赖，且仅适用于开发环境。

#### 配置

```yaml
memory:
  vector_enabled: true
  vector_backend: weaviate
  weaviate:
    host: localhost
    port: 8090
    grpc_port: 50061
    embedded: false
    vector_size: 768
    schema_class: CXHMSMemory
    api_key: null
```

### 4.3 CosyVoice（语音合成，可选）

CosyVoice 是阿里开源的语音合成系统，支持指令式语音生成。

**端口**：50000（默认）

**部署步骤**：

```bash
cd cosyvoice

# 安装依赖
pip install -r requirements.txt

# 下载模型
python download_models.py

# 启动服务（FastAPI 模式）
cd runtime/python/fastapi
python server.py
```

**Docker 部署**：

```bash
cd cosyvoice
docker build -t cosyvoice -f docker/Dockerfile .
docker run -d --gpus all -p 50000:50000 cosyvoice
```

**配置**：

在 `config/default.yaml` 中：

```yaml
tts:
  mode: remote
  cosyvoice:
    url: http://127.0.0.1:50000
    model: CosyVoice2-0.5B
    default_mode: instruct2
    timeout: 120
    default_spk_id: "中文女"
```

### 4.4 F5-TTS（语音合成，可选）

F5-TTS 是零样本语音克隆系统，支持参考音频克隆。

**端口**：5000（默认）

#### 方式一：PyTorch 推理

```bash
cd f5-fast/inference_service
pip install -r ../requirements.txt
python main_pytorch.py
```

#### 方式二：TensorRT-LLM 加速推理（Linux + NVIDIA GPU）

```bash
cd f5-fast
docker-compose up -d
```

Docker Compose 会启动两个服务：
- `inference-service`：TensorRT-LLM 推理引擎（端口 8000）
- `gateway`：FastAPI 网关（端口 18081）

**配置**：

```yaml
tts:
  mode: remote
  remote_url: http://127.0.0.1:5000
  engine: f5-tts
  f5_tts:
    url: http://127.0.0.1:5000
    timeout: 120
```

### 4.5 IndexTTS（语音合成，可选）

IndexTTS 是另一种语音合成引擎，CX-O-SERVER 支持自动启停。

**端口**：8004（默认）

**配置**：

```yaml
services:
  index_tts:
    url: http://127.0.0.1:8004
    timeout: 180
    enabled: true
    auto_stop_delay: 300
    start_command: "python -m index_tts.app --port 8004 --host 0.0.0.0"
    working_dir: "index-tts"
```

当 `enabled: true` 时，CX-O-SERVER 会在需要时自动启动 IndexTTS 进程，空闲 `auto_stop_delay` 秒后自动停止。

---

## 5. 配置说明

CX-O 采用 **配置文件 + 环境变量** 的混合配置方式，环境变量优先级高于配置文件。

### 5.1 配置文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `config/default.yaml` | 项目根目录 | 主配置文件（YAML 格式） |
| `CX-O-SERVER/config.json` | CX-O-SERVER 目录 | Pydantic 配置模型读取的 JSON 配置 |
| `CX-O-VoiceWorkStation/config.yaml` | VoiceWorkStation 目录 | 语音工作站配置 |

### 5.2 环境变量

所有环境变量以 `CXO_` 为前缀，支持层级覆盖：

| 环境变量 | 对应配置项 | 说明 |
|----------|-----------|------|
| `CXO_CONFIG` | — | 配置文件路径 |
| `CXO_SYSTEM_HOST` | `system.host` | 服务监听地址 |
| `CXO_SYSTEM_PORT` | `system.port` | 服务监听端口 |
| `CXO_SYSTEM_DEBUG` | `system.debug` | 调试模式 |
| `CXO_SYSTEM_LOG_LEVEL` | `system.log_level` | 日志级别 |
| `CXO_SYSTEM_WORKERS` | `system.workers` | 工作进程数 |
| `CXO_GATEWAY_HOST` | `gateway.host` | Gateway 监听地址 |
| `CXO_GATEWAY_PORT` | `gateway.port` | Gateway 监听端口 |
| `CXO_LLM_PROVIDER` | `llm.provider` | LLM 提供商 |
| `CXO_LLM_HOST` | `llm.host` | LLM 服务地址 |
| `CXO_LLM_MODEL` | `llm.model` | LLM 模型名称 |
| `CXO_LLM_API_KEY` | `llm.api_key` | LLM API 密钥 |
| `CXO_ASR_MODE` | `asr.mode` | ASR 模式（`embedded` / `remote`） |
| `CXO_ASR_MODEL_DIR` | `asr.model_dir` | ASR 模型目录 |
| `CXO_ASR_DEVICE` | `asr.device` | ASR 设备（`cuda` / `cpu`） |
| `CXO_ASR_REMOTE_URL` | `asr.remote_url` | 远程 ASR 服务地址 |
| `CXO_TTS_MODE` | `tts.mode` | TTS 模式（`embedded` / `remote`） |
| `CXO_TTS_MODEL_DIR` | `tts.model_dir` | TTS 模型目录 |
| `CXO_TTS_DEVICE` | `tts.device` | TTS 设备 |
| `CXO_TTS_REMOTE_URL` | `tts.remote_url` | 远程 TTS 服务地址 |
| `CXO_DATABASE_PATH` | `database.path` | 主数据库路径 |
| `CXO_MEMORY_VECTOR_BACKEND` | `memory.vector_backend` | 向量存储后端 |
| `CXO_LOG_LEVEL` | `logging.level` | 日志级别 |

### 5.3 核心配置项说明

#### 系统配置

```yaml
system:
  host: 0.0.0.0       # 监听地址
  port: 8000           # 监听端口
  debug: false         # 调试模式
  log_level: INFO      # 日志级别: DEBUG/INFO/WARNING/ERROR
  workers: 1           # Uvicorn 工作进程数
```

#### LLM 配置

```yaml
llm:
  provider: ollama           # ollama / vllm / openai / anthropic / deepseek
  host: http://localhost:11434
  model: qwen3:latest
  temperature: 0.7
  max_tokens: 4096
  stream: true               # 是否启用流式输出
  api_key: null              # OpenAI/Anthropic/DeepSeek 需要
```

项目支持多模型配置，可为不同任务指定不同模型：

```yaml
models:
  main:
    provider: ollama
    model: qwen3:latest
  summary:
    provider: ollama
    model: qwen3:latest
    max_tokens: 131072       # 摘要任务需要更大的 token 限制
  memory:
    provider: ollama
    model: qwen3:latest
    max_tokens: 131072
model_defaults:
  summary: main              # 摘要任务默认使用 main 模型
  memory: main               # 记忆任务默认使用 main 模型
```

#### ASR 配置

```yaml
asr:
  mode: remote               # embedded: 本地 SenseVoice | remote: 远程服务
  model_dir: SenseVoiceSmall # embedded 模式的模型目录
  device: cuda               # embedded 模式的设备
  remote_url: http://127.0.0.1:8001  # remote 模式的服务地址
  language: auto             # 语言识别: auto/zh/en/ja/ko
```

#### TTS 配置

```yaml
tts:
  mode: remote               # embedded: 本地 F5-TTS | remote: 远程服务
  model_dir: F5TTS_v1_Base   # embedded 模式的模型目录
  device: cuda               # embedded 模式的设备
  remote_url: http://127.0.0.1:5000  # remote 模式的服务地址
  speed: 1.0                 # 语速
  cross_fade_duration: 0.15  # 交叉淡化时长
  emotion_enabled: true      # 情感语音
  effects_enabled: true      # 音效
```

#### 记忆配置

```yaml
memory:
  decay_enabled: true           # 记忆衰减
  batch_interval: 3600          # 批量处理间隔（秒）
  permanent_threshold: 0.95     # 永久记忆阈值
  max_short_term_age_days: 7    # 短期记忆最大天数
  max_long_term_age_days: 365   # 长期记忆最大天数
  vector_enabled: true          # 向量搜索
  vector_backend: weaviate      # weaviate / weaviate_embedded
  archive_enabled: true         # 归档
  dedup_threshold: 0.85         # 去重阈值
```

#### 数据库配置

```yaml
database:
  path: data/cxo.db             # 主数据库（SQLite）
  memories_db: data/memories.db # 记忆数据库
  sessions_db: data/sessions.db # 会话数据库
  acp_db: data/acp              # ACP 数据目录
  pool_size: 10
  max_overflow: 20
```

#### 图数据库配置

```yaml
graph:
  enabled: true
  database_path: data/graph.db
  auto_create_schema: true
  weaviate:
    url: http://localhost:8080
    vector_dim: 384
    batch_size: 100
  embedding:
    model: sentence-transformers/all-MiniLM-L6-v2
    device: cpu
```

### 5.4 前端配置

前端通过 `.env` 文件配置，复制 `.env.example` 并修改：

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_CONTROL_SERVICE_URL=http://localhost:8765
VITE_VOICE_WS_URL=http://127.0.0.1:8200
VITE_REQUEST_TIMEOUT=30
VITE_LOG_LEVEL=info
```

> **注意**：`VITE_API_URL` 和 `VITE_WS_URL` 应指向 CX-O-SERVER 的实际地址和端口。如果 Gateway 端口单独配置为 8100，则相应修改。

---

## 6. 常见问题排查

### 6.1 启动问题

**Q: CX-O-SERVER 启动报错 `ModuleNotFoundError: No module named 'server'`**

A: 需要设置 `PYTHONPATH` 为项目根目录：

```bash
cd CX-O-SERVER
set PYTHONPATH=%CD%\..
python -m server.main
```

**Q: Python 版本不满足要求**

A: 项目要求 Python 3.11+。使用 `create-env.bat` 可自动创建虚拟环境：

```bat
create-env.bat
```

手动创建：

```bash
python -m venv py311
call py311\Scripts\activate.bat
pip install -r requirements.txt
```

**Q: `pip install` 安装 PyTorch 相关依赖失败**

A: PyTorch 需要指定 CUDA 版本的索引。CosyVoice 的 `requirements.txt` 已包含：

```
--extra-index-url https://download.pytorch.org/whl/cu121
```

如需其他 CUDA 版本，参考 [PyTorch 官网](https://pytorch.org/get-started/locally/) 选择对应版本。

### 6.2 LLM 相关

**Q: Ollama 连接失败**

A: 检查以下几点：
1. Ollama 服务是否运行：`ollama list`
2. 端口是否正确：默认 `http://localhost:11434`
3. 模型是否已拉取：`ollama pull qwen3:latest`
4. 如 Ollama 运行在其他机器，修改 `CXO_LLM_HOST` 环境变量

**Q: LLM 响应速度慢**

A: 可能的优化方向：
1. 使用更小的模型（如 `qwen3:4b`）
2. 使用 vLLM 替代 Ollama 以获得更高吞吐
3. 使用 GPU 推理（确保 CUDA 可用）
4. 调整 `max_tokens` 和 `temperature` 参数

### 6.3 语音相关

**Q: ASR/TTS 服务不可用**

A: CX-O-SERVER 支持两种模式：
- `embedded`：本地加载模型，需要 GPU 和模型文件
- `remote`：连接远程服务，需要先启动对应的 ASR/TTS 服务

如果本地 GPU 不可用，将配置改为 `mode: remote` 并启动对应的远程服务。

**Q: Embedded ASR 初始化失败，自动降级到 remote 模式**

A: 这是正常行为。CX-O-SERVER 会在 embedded 模式初始化失败时自动降级到 remote 模式。检查日志中的具体错误信息，常见原因：
1. 模型文件不存在：确认 `SenseVoiceSmall` 目录在正确位置
2. CUDA 不可用：确认 NVIDIA 驱动和 CUDA 已正确安装
3. VRAM 不足：尝试释放其他 GPU 进程

**Q: CosyVoice 服务启动失败**

A: CosyVoice 依赖较多，确保：
1. 完整安装 `cosyvoice/requirements.txt` 中的依赖
2. 已运行 `python download_models.py` 下载模型
3. GPU VRAM >= 8GB
4. Linux 环境下 deepspeed 才可安装

### 6.4 向量数据库相关

**Q: Weaviate 连接失败**

A: 检查：
1. Docker 容器是否运行：`docker ps | grep weaviate`
2. 端口映射是否正确：项目默认使用 `8090`（REST）和 `50061`（gRPC）
3. 健康检查：`curl http://localhost:8090/v1/.well-known/ready`
4. 如不需要向量搜索，可设置 `memory.vector_enabled: false`

**Q: 向量同步失败**

A: 首次启动时 CX-O-SERVER 会尝试将 SQLite 中的记忆同步到 Weaviate。如果 Weaviate 未就绪，同步会失败但不影响基本功能。等待 Weaviate 完全启动后重启 CX-O-SERVER 即可。

### 6.5 前端相关

**Q: 前端无法连接后端**

A: 检查 `.env` 文件中的配置：
1. `VITE_API_URL` 是否指向正确的 CX-O-SERVER 地址
2. `VITE_WS_URL` 是否指向正确的 WebSocket 地址
3. 后端 CORS 配置是否允许前端域名
4. 修改 `.env` 后需要重启前端开发服务器

**Q: `npm install` 失败**

A: 尝试：
1. 清除缓存：`npm cache clean --force`
2. 删除 `node_modules` 和 `package-lock.json` 后重新安装
3. 使用国内镜像：`npm config set registry https://registry.npmmirror.com`

### 6.6 端口冲突

项目默认使用的端口：

| 端口 | 服务 |
|------|------|
| 8000 | CX-O-SERVER（API + WebSocket） |
| 8200 | CX-O-VoiceWorkStation |
| 5173 | CX-O-Frontend（Vite 开发服务器） |
| 11434 | Ollama |
| 8090 | Weaviate REST API |
| 50061 | Weaviate gRPC API |
| 5000 | F5-TTS 服务 |
| 50000 | CosyVoice 服务 |
| 8001 | 远程 ASR 服务 |
| 8004 | IndexTTS 服务 |
| 8765 | Control 服务 |
| 9996 | CXFC 发现端口 |
| 9997 | CXFC 广播端口 |
| 9998 | ACP 广播端口 |
| 9999 | ACP 发现端口 |
| 10000 | ACP 连接端口 |
| 10001 | ACP 群组端口 |

如遇端口冲突，通过环境变量或配置文件修改对应端口。

### 6.7 数据目录

CX-O-SERVER 的数据目录结构：

```
CX-O-SERVER/data/
├── acp/                    # ACP 协议数据
├── effects/                # 音效文件
├── voice_refs/             # 语音参考文件
│   ├── emotions/           # 情感语音参考
│   └── transitions/        # 过渡语音参考
├── agents.json             # Agent 配置
├── memories.db             # 记忆数据库（SQLite）
└── sessions.db             # 会话数据库（SQLite）
```

项目根目录数据：

```
data/
├── acp/                    # ACP 数据（agents.yaml, connections.yaml, groups.yaml）
├── agents.json
├── memories.db
└── sessions.db
```

> **注意**：数据库文件会在首次运行时自动创建，无需手动初始化。

---

## 附录：服务架构概览

```
┌─────────────────────────────────────────────────────┐
│                   CX-O-Frontend                      │
│              (React + Vite, :5173)                   │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / WebSocket
                       ▼
┌─────────────────────────────────────────────────────┐
│                   CX-O-SERVER                        │
│          (FastAPI + Uvicorn, :8000)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ API 路由  │ │ Gateway  │ │ WebSocket│            │
│  └──────────┘ └──────────┘ └──────────┘            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ 记忆管理  │ │ 上下文   │ │ LLM 客户端│            │
│  └──────────┘ └──────────┘ └──────────┘            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │ ASR 服务  │ │ TTS 服务  │ │ 图数据库  │            │
│  └──────────┘ └──────────┘ └──────────┘            │
└──────┬───────────┬──────────────┬───────────────────┘
       │           │              │
       ▼           ▼              ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│  Ollama   │ │ Weaviate │ │ VoiceWork-   │
│ (:11434)  │ │ (:8090)  │ │ Station      │
│           │ │          │ │ (:8200)      │
└──────────┘ └──────────┘ └──────┬───────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              ┌──────────┐ ┌────────┐ ┌─────────┐
              │CosyVoice │ │F5-TTS  │ │IndexTTS │
              │(:50000)  │ │(:5000) │ │(:8004)  │
              └──────────┘ └────────┘ └─────────┘
```
