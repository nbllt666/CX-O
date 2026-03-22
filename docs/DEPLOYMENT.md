# CX-O 部署指南

## 目录

1. [环境要求](#环境要求)
2. [目录结构](#目录结构)
3. [安装步骤](#安装步骤)
4. [服务配置](#服务配置)
5. [启动服务](#启动服务)
6. [Docker 部署](#docker-部署)
7. [生产环境配置](#生产环境配置)
8. [故障排除](#故障排除)

---

## 环境要求

### 系统要求

- **操作系统**：Windows 10/11
- **Python**：3.10+
- **Node.js**：18+
- **Miniconda3**：项目内置

### 硬件要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| CPU | 4 核 | 8 核+ |
| 内存 | 8GB | 16GB+ |
| 显存 | - | 8GB+ (用于 LLM) |
| 磁盘 | 20GB | 50GB+ SSD |

### 依赖服务

- **Ollama**：本地 LLM 服务（http://localhost:11434）
- **向量存储**（可选）：
  - Milvus Lite：嵌入式，无需额外服务
  - ChromaDB：本地向量库
  - Qdrant：需要独立部署

---

## 目录结构

```
CX-O/
├── cx-o-gateway/          # WebSocket 网关服务 (Port 8100)
├── cx-o-frontend/         # React 前端 (Port 5173)
├── CXHMS/                 # 后端核心服务 (Port 8000)
│   ├── backend/
│   │   ├── api/          # FastAPI 路由
│   │   └── core/         # 核心模块
│   └── config/           # 配置文件
├── SenseVoice/            # ASR 语音识别 (Port 8001)
├── F5-TTS/               # TTS 语音合成 (Port 8002)
├── CosyVoice/            # 备用 TTS
├── data/                  # 数据目录
│   ├── acp/              # ACP 配置
│   └── voice_refs/        # 音频参考文件
└── docs/                  # 文档
```

---

## 安装步骤

### 1. 安装 Miniconda3

项目已包含 Miniconda3，位于 `d:\CX-O\miniconda3\`

### 2. 创建并激活环境

```batch
d:\CX-O\7.激活conda环境.bat
```

### 3. 安装 Python 依赖

```batch
d:\CX-O\2-2.安装依赖.bat
```

### 4. 安装 Node.js 依赖

```batch
d:\CX-O\install-npm.bat
```

### 5. 下载模型

```batch
d:\CX-O\download-cosyvoice-models.bat
```

---

## 服务配置

### CXHMS 配置

**文件**：`CXHMS/config/default.yaml`

```yaml
server:
  host: 0.0.0.0
  port: 8000

models:
  main:
    provider: ollama
    host: http://localhost:11434
    model: qwen3-vl:8b
    temperature: 0.7
    max_tokens: 0
```

### Gateway 配置

**文件**：`cx-o-gateway/config.json`

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "services": {
    "cxhms": {
      "url": "ws://127.0.0.1:8000/ws",
      "http_url": "http://127.0.0.1:8000",
      "timeout": 60
    },
    "asr": {
      "url": "http://127.0.0.1:8001",
      "timeout": 120
    },
    "tts": {
      "url": "http://127.0.0.1:8002",
      "timeout": 120
    }
  }
}
```

### VAD 配置

**文件**：`CXHMS/config/vad.yaml`

```yaml
vad:
  mode: "webrtc"
  sample_rate: 16000
  frame_duration_ms: 30
  silence_threshold_ms: 500
  speech_threshold_ms: 300

agent_interrupt:
  enabled: true
  interrupt_threshold_ms: 500
  min_speech_duration_ms: 1000
  interrupt_cooldown_ms: 3000
```

### 弹幕防火墙配置

**文件**：`CXHMS/config/firewall_v3.yaml`

```yaml
interrupt:
  enabled: true
  mode: "main_llm"
  main_llm:
    enabled: true
    prompt: "判断是否需要打断..."
  independent_llm:
    enabled: false
    model: "qwen2.5:1.5b"
```

---

## 启动服务

### 一键启动

```batch
d:\CX-O\1-1.start-all.bat
```

这将启动所有服务：
- CXHMS Backend (Port 8000)
- SenseVoice ASR (Port 8001)
- F5-TTS (Port 8002)
- CX-O Gateway (Port 8100)
- Frontend (Port 5173)

### 单独启动服务

```batch
# 启动 CXHMS 后端
cd d:\CX-O\CXHMS
python -m uvicorn backend.api.app:app --host 0.0.0.0 --port 8000

# 启动 SenseVoice
cd d:\CX-O\SenseVoice
python api.py

# 启动 F5-TTS
cd d:\CX-O\F5-TTS
python webapi.py

# 启动 Gateway
cd d:\CX-O\cx-o-gateway
python main.py

# 启动前端
cd d:\CX-O\cx-o-frontend
npm run dev
```

### 停止所有服务

```batch
d:\CX-O\1-2.stop-all.bat
```

---

## Docker 部署

### 使用 Docker Compose

#### 1. 构建镜像

```bash
docker-compose build
```

#### 2. 启动服务

```bash
docker-compose up -d
```

#### 3. 查看日志

```bash
docker-compose logs -f
```

#### 4. 停止服务

```bash
docker-compose down
```

### 各服务 Dockerfile 位置

| 服务 | Dockerfile |
|------|-----------|
| CXHMS | `CXHMS/Dockerfile` |
| SenseVoice | `SenseVoice/Dockerfile` |
| F5-TTS | `F5-TTS/Dockerfile` |
| Gateway | `cx-o-gateway/` (需创建) |

---

## 生产环境配置

### 1. 安全配置

#### 启用 API 密钥

```yaml
security:
  api_key_enabled: true
  api_key: "your-secure-api-key"
```

#### 限制 CORS

```json
{
  "gateway": {
    "cors": {
      "allow_origins": ["https://yourdomain.com"]
    }
  }
}
```

### 2. 高可用配置

```
                    ┌─────────────┐
                    │   Nginx     │
                    │ (负载均衡)  │
                    └──────┬──────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
   │ Gateway1 │       │ Gateway2 │       │ Gateway3 │
   │ Port8100 │       │ Port8101 │       │ Port8102 │
   └────┬────┘       └────┬────┘       └────┬────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
        ┌─────▼─────┐           ┌──────▼──────┐
        │   CXHMS   │           │   CXHMS    │
        │  Backend1 │           │  Backend2  │
        │  Port8000 │           │  Port8001  │
        └───────────┘           └────────────┘
```

### 3. 性能优化

#### LLM 推理优化

使用 VLLM 替代 Ollama：

```yaml
models:
  main:
    provider: vllm
    host: http://localhost:8000
    model: qwen2.5:14b
    temperature: 0.7
    max_tokens: 4096
```

#### 向量搜索优化

```yaml
memory:
  vector_enabled: true
  vector_backend: "qdrant"  # 替代 milvus_lite
```

### 4. 监控配置

```yaml
monitoring:
  enabled: true
  metrics_enabled: true
  health_check_enabled: true
  performance_logging: true
```

---

## 故障排除

### 常见问题

#### 1. 端口被占用

```batch
netstat -ano | findstr "8000 8001 8002 8100 5173"
```

找到占用端口的进程 PID 后，结束进程：

```batch
taskkill /PID <PID> /F
```

#### 2. 模型加载失败

- SenseVoice/F5-TTS 首次启动会下载模型
- 确保网络连接正常
- 检查模型文件是否完整

#### 3. 前端无法连接

检查网关是否正常运行：
```bash
curl http://127.0.0.1:8100/health
```

### 日志位置

| 服务 | 日志位置 |
|------|---------|
| CXHMS | `CXHMS/logs/app.log` |
| Gateway | `cx-o-gateway/logs/` |
| SenseVoice | 控制台输出 |
| F5-TTS | 控制台输出 |

### 服务健康检查

| 服务 | 检查地址 |
|------|---------|
| Gateway | http://127.0.0.1:8100/health |
| CXHMS | http://127.0.0.1:8000/health |
| SenseVoice | http://127.0.0.1:8001/health |
| F5-TTS | http://127.0.0.1:8002/health |

---

## 快速参考

### 服务端口

| 服务 | 端口 | 协议 |
|------|------|------|
| Gateway | 8100 | WebSocket/HTTP |
| CXHMS | 8000 | WebSocket/HTTP |
| SenseVoice | 8001 | HTTP |
| F5-TTS | 8002 | HTTP |
| Frontend | 5173 | HTTP |

### 启动命令

```batch
# 一键启动
d:\CX-O\1-1.start-all.bat

# 一键停止
d:\CX-O\1-2.stop-all.bat

# 激活 conda 环境
d:\CX-O\7.激活conda环境.bat
```

### 访问地址

- 管理控制台：http://127.0.0.1:5173
- Gateway API：http://127.0.0.1:8100
- CXHMS API：http://127.0.0.1:8000
