# CX-O 系统架构

## 整体架构图

CX-O 采用分布式微服务架构，由多个独立服务组成，各服务通过 HTTP/WebSocket 进行通信。

```mermaid
graph TB
    subgraph Frontend["前端"]
        FE[CX-O Frontend<br/>Port: 5173]
    end

    subgraph Gateway["CX-O Gateway (8100)"]
        WS[WebSocket Gateway]
        subgraph Handlers["Handlers"]
            CH[Chat Handler]
            MH[Memory Handler]
            AH[Audio Handler]
            LH[Live Handler]
            TH[Tools Handler]
            ACPH[ACP Handler]
            MP[MCP Handler]
        end
        subgraph Services["Services Layer"]
            CXHMS_CLIENT[CXHMS Client]
            TTS_CLIENT[TTS Client]
            ASR_CLIENT[ASR Client]
            VAD[VAD Processor]
            FIREWALL[Firewall]
            INTERRUPT[Interrupt Manager]
        end
    end

    subgraph Backend["CXHMS Backend (8000)"]
        REST_API[REST API]
        subgraph Core["Core Layer"]
            LLM[LLM Client]
            MEMORY[Memory Manager]
            CONTEXT[Context Manager]
            TOOLS[Tool Registry]
            ACP[ACP Manager]
            SESSION[Session Manager]
        end
        subgraph Storage["Storage Layer"]
            SQLITE[(SQLite)]
            VECTOR[(Vector DB)]
        end
    end

    subgraph VoiceServices["语音服务"]
        SENSEVOICE[SenseVoice ASR<br/>8001]
        F5TTS[F5-TTS TTS<br/>8002]
    end

    FE --> WS
    WS --> CH
    WS --> MH
    WS --> AH
    WS --> LH
    WS --> TH
    WS --> ACPH
    WS --> MP

    CH --> CXHMS_CLIENT
    MH --> CXHMS_CLIENT
    AH --> ASR_CLIENT
    AH --> TTS_CLIENT
    AH --> VAD
    AH --> INTERRUPT
    LH --> FIREWALL

    CXHMS_CLIENT --> REST_API
    REST_API --> LLM
    REST_API --> MEMORY
    REST_API --> TOOLS
    REST_API --> ACP

    LLM --> SQLITE
    MEMORY --> SQLITE
    MEMORY --> VECTOR
```

## 模块职责

### CX-O Gateway (端口 8100)

**职责**：统一入口，处理前端所有请求，协调各服务。

**核心组件**：

| 层级 | 组件 | 职责 |
|------|------|------|
| Gateway | WebSocket Server | 前端通信、统一入口 |
| Handlers | Chat/Memory/Audio/Live | 消息处理路由 |
| Services | CXHMS/TTS/ASR Clients | HTTP 客户端调用后端服务 |
| Services | VAD/Firewall/Interrupt | 音频处理和打断管理 |

### CXHMS Backend (端口 8000)

**职责**：核心 AI 服务，提供记忆管理、工具调用、ACP 协议等。

**核心组件**：

| 层级 | 组件 | 职责 |
|------|------|------|
| API | REST API | HTTP 接口 |
| Core | LLM Client | Ollama/VLLM 客户端封装 |
| Core | Memory Manager | 记忆 CRUD、向量搜索、衰减计算 |
| Core | Context Manager | 会话管理、消息历史、上下文摘要 |
| Core | Tool Registry | 工具注册、发现、调用 |
| Core | ACP Manager | Agent 发现、连接、群组、消息传递 |

## 数据流

### 语音对话流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant FE as Frontend
    participant Gateway as Gateway
    participant CXHMS as CXHMS
    participant ASR as SenseVoice
    participant LLM as LLM
    participant TTS as F5-TTS

    User->>FE: 音频数据
    FE->>Gateway: WebSocket 音频
    Gateway->>ASR: HTTP 音频识别
    ASR-->>Gateway: 文本
    Gateway->>CXHMS: HTTP 聊天请求
    CXHMS->>LLM: 发送文本
    LLM-->>CXHMS: 回复文本
    CXHMS-->>Gateway: 回复文本
    Gateway->>TTS: HTTP 语音合成
    TTS-->>Gateway: 合成音频
    Gateway-->>FE: WebSocket 音频流
    FE->>User: 播放音频
```

### 全双工打断流程

#### 场景 1：用户打断 Agent

```mermaid
flowchart TD
    A[Agent TTS 播放中] --> B[用户说话]
    B --> C[VAD 检测]
    C --> D[ASR 识别]
    D --> E[LLM 判断]
    E --> F{需要打断?}
    F -->|是| G[停止 TTS]
    F -->|否| H[继续播放]
    G --> I[生成新回复]
    I --> J[开始新 TTS]
    H --> K[播放完成]
```

#### 场景 2：Agent 打断用户

```mermaid
flowchart TD
    A[用户说话中] --> B[实时 ASR 流]
    B --> C[LLM 实时判断]
    C --> D{可以插话?}
    D -->|是| E[打断用户音频]
    D -->|否| F[继续监听]
    E --> G[开始 TTS 回复]
    F --> A
```

## 协议设计

### WebSocket 消息格式

**请求**：
```json
{
  "type": "request",
  "action": "module.action",
  "request_id": "uuid-string",
  "data": {}
}
```

**响应**：
```json
{
  "type": "response",
  "request_id": "uuid-string",
  "action": "module.action",
  "status": "success",
  "data": {}
}
```

### Action 命名空间

| 命名空间 | 描述 |
|---------|------|
| chat.* | 聊天相关操作 |
| memory.* | 记忆相关操作 |
| tools.* | 工具相关操作 |
| acp.* | ACP 协议操作 |
| mcp.* | MCP 协议操作 |
| asr.* | 语音识别操作 |
| tts.* | 语音合成操作 |
| config.* | 配置操作 |
| metrics.* | 指标操作 |
| system.* | 系统操作 |

## 存储架构

### SQLite（结构化数据）
- 记忆内容
- 会话消息
- ACP 连接信息

### 向量存储（可选）
- **Milvus Lite**：轻量级向量数据库
- **ChromaDB**：本地向量库
- **Qdrant**：生产级向量服务

### 文件存储
- 音频参考文件：`data/voice_refs/`
- 音效文件：`data/effects/`
- 备份文件：`data/backups/`

## 配置管理

### CXHMS 配置

文件：`CXHMS/config/default.yaml`

```yaml
server:
  host: "0.0.0.0"
  port: 8000

llm:
  provider: "ollama"
  host: "http://localhost:11434"
  model: "qwen3-vl:8b"

memory:
  enabled: true
  vector_enabled: true
  vector_backend: "milvus_lite"

acp:
  enabled: true
  agent_id: "cxhms_agent_001"
  discovery_enabled: true
```

### Gateway 配置

文件：`cx-o-gateway/config.json`

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "services": {
    "cxhms": {
      "url": "http://127.0.0.1:8000"
    },
    "sensevoice": {
      "url": "http://127.0.0.1:8001"
    },
    "f5tts": {
      "url": "http://127.0.0.1:8002"
    }
  }
}
```

## 目录结构

```
CX-O/
├── CXHMS/                    # CXHMS 后端服务
│   ├── backend/
│   │   ├── api/
│   │   │   ├── app.py        # FastAPI 应用
│   │   │   ├── routers/     # 路由模块
│   │   │   └── middleware/  # 中间件
│   │   ├── core/
│   │   │   ├── llm/         # LLM 客户端
│   │   │   ├── memory/      # 记忆系统
│   │   │   ├── context/     # 上下文管理
│   │   │   ├── tools/       # 工具系统
│   │   │   ├── acp/         # ACP 协议
│   │   │   └── ...
│   │   └── tests/
│   ├── config/
│   └── docs/
│
├── cx-o-gateway/             # 网关服务
│   ├── gateway/
│   │   ├── server.py
│   │   └── config.py
│   ├── handlers/             # 消息处理器
│   │   ├── chat.py
│   │   ├── audio.py
│   │   └── ...
│   ├── services/             # 服务客户端
│   │   ├── cxhms_client.py
│   │   ├── tts_client.py
│   │   ├── asr_client.py
│   │   └── ...
│   └── protocol/
│       ├── message.py
│       └── actions.py
│
├── cx-o-frontend/            # 前端界面
│   └── src/
│
├── SenseVoice/               # ASR 服务
├── F5-TTS/                  # TTS 服务
├── CosyVoice/               # 备用 TTS
├── F5-fast/                 # F5-TTS 推理优化
│
└── docs/                    # 文档
```

## 技术栈

- **框架**：Python 3.10+, FastAPI, uvicorn, WebSocket
- **AI 服务**：SenseVoice（ASR）、F5-TTS（TTS）
- **LLM**：Ollama、VLLM
- **数据库**：SQLite、Milvus Lite、ChromaDB
- **前端**：React 18+, TypeScript, Tailwind CSS, Zustand
- **协议**：MCP（Model Context Protocol）、ACP

## 扩展性设计

### MCP 工具系统

支持通过 MCP（Model Context Protocol）扩展工具能力。

### Agent 系统

- 多 Agent 支持
- Agent 克隆
- Agent 专属会话

### 模型路由

- 主模型（main）：通用对话
- 摘要模型（summary）：上下文摘要
- 记忆模型（memory）：记忆处理
