# CX-O 智能语音对话系统

基于单体应用架构的智能语音对话系统，集成语音识别（ASR）、大语言模型（LLM）和语音合成（TTS）能力，支持双向全双工语音交互。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Frontend                              │
│                   (React + TypeScript)                          │
│                      http://127.0.0.1:5173                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket / HTTP
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CX-O Server (8100)                           │
│              单体应用，集成所有功能                               │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Gateway Layer: WebSocket、HTTP REST API                 │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │  Handlers Layer: 聊天、记忆、音频、工具、ACP、MCP         │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │  Services Layer: ASR、TTS、VAD、防火墙、打断管理          │  │
│  ├─────────────────────────────────────────────────────────┤  │
│  │  Core Layer: LLM、记忆、上下文、工具、ACP、图谱           │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## 功能特性

- **语音对话**：端到端语音交互，ASR → LLM → TTS 全流程
- **智能记忆**：长期记忆存储、语义搜索、自动遗忘衰减机制
- **多模型支持**：Ollama 本地模型，可扩展支持 VLLM 等其他 LLM
- **工具生态**：MCP（Model Context Protocol）协议支持，内置多种工具
- **ACP 协议**：局域网自动发现、点对点通信、群组协同
- **弹幕系统**：B站/RDF 弹幕接入，三档防火墙（block/passive/reply）
- **双向全双工**：支持用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**：WebRTC/Energy/Silero 多种模式
- **情感 TTS**：支持多种情感音色的语音合成
- **知识图谱**：语义节点存储、关系管理、图遍历查询

## 快速开始

### 环境要求

- Windows 10/11 或 Linux
- Python 3.10+
- Node.js 18+
- CUDA 11.8+ (GPU 支持)
- Miniconda3

### 启动服务

#### Windows 一键启动

```batch
.\start-all.bat
```

#### 手动启动

1. **启动后端服务**
```batch
python main.py
```

2. **启动前端**
```batch
cd frontend
npm run dev
```

### 访问界面

- 前端界面: http://127.0.0.1:5173
- API 文档: http://127.0.0.1:8100/docs

## 服务端口

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CX-O Server | 8100 | WebSocket/HTTP | 单体应用，集成所有功能 |
| CX-O Frontend | 5173 | HTTP | Web 前端 |

## 项目结构

```
CX-O/
├── backend/                    # 后端服务（单体应用）
│   ├── api/routers/           # API 路由
│   │   ├── chat.py            # 聊天接口
│   │   ├── memory.py          # 记忆管理
│   │   ├── agents.py          # Agent 管理
│   │   ├── tools.py           # 工具管理
│   │   ├── acp.py             # ACP 协议
│   │   └── ...
│   └── core/                  # 核心模块
│       ├── memory/            # 记忆系统
│       ├── llm/               # LLM 客户端
│       ├── tools/             # 工具系统
│       ├── acp/               # ACP 协议
│       ├── graph/             # 知识图谱
│       ├── asr/               # ASR 服务
│       ├── tts/               # TTS 服务
│       └── ...
│
├── gateway/                   # Gateway 模块
│   ├── gateway/               # WebSocket 网关
│   ├── handlers/              # 消息处理器
│   └── services/              # 服务客户端
│
├── frontend/                  # 前端界面
│   └── src/
│
├── sensevoice/               # 语音识别模型
├── f5-tts/                   # 语音合成模型
├── f5-fast/                  # F5-TTS 快速推理
├── cosyvoice/                # 备用语音合成
│
├── config/                   # 配置文件
│   └── default.yaml          # 主配置
│
└── docs/                     # 项目文档
```

## 文档

- [项目概述](docs/PROJECT_OVERVIEW.md)
- [架构文档](docs/ARCHITECTURE.md)
- [API 文档](docs/API.md)
- [部署指南](docs/DEPLOYMENT.md)
- [语音服务文档](docs/VOICE_SERVICES.md)

## 技术栈

- **框架**: Python 3.10+, FastAPI, uvicorn, WebSocket
- **AI 服务**: SenseVoice（ASR）、F5-TTS（TTS）
- **LLM**: Ollama、VLLM
- **数据库**: SQLite、Milvus Lite、ChromaDB
- **前端**: React 18+, TypeScript, Tailwind CSS, Zustand
- **协议**: MCP（Model Context Protocol）、ACP

## License

MIT
