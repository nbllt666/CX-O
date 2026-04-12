# CX-O 智能语音对话系统

## 项目简介

**CX-O** (晨曦语音对话系统) 是一个智能语音对话平台，集成了语音识别（ASR）、大语言模型（LLM）和语音合成（TTS）能力，支持双向全双工语音交互。

## 系统架构

CX-O 采用分布式微服务架构，由多个独立服务组成：

```
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Frontend                              │
│                   (React + TypeScript)                          │
│                      http://127.0.0.1:5173                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket / HTTP
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CX-O Gateway (8100)                          │
│              WebSocket 网关、协议解析、服务路由                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
           ▼               ▼               ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │  CXHMS   │    │SenseVoice│    │  F5-TTS  │
    │ (8000)   │    │  ASR     │    │   TTS    │
    └──────────┘    └──────────┘    └──────────┘
```

## 核心组件

### CXHMS 后端服务 (端口 8000)

CXHMS (CX-O History & Memory Service) 是系统的核心AI服务，提供：

- **记忆管理系统**：长期记忆存储、语义搜索、自动遗忘衰减机制
- **工具系统**：MCP 协议支持、内置工具、动态注册
- **ACP 协议**：局域网自动发现、点对点通信、群组协同
- **对话系统**：流式响应、RAG检索增强、多Agent支持、多模态视觉
- **LLM 路由**：支持 Ollama、VLLM 等多种 LLM 提供商

### CX-O Gateway 网关服务 (端口 8100)

- **WebSocket 网关**：统一入口，处理前端所有请求
- **协议解析**：WebSocket 消息格式解析、Action 路由
- **服务协调**：与 CXHMS、SenseVoice、F5-TTS 通信
- **音频处理**：音频流管理、TTS 流式播放

### CX-O Frontend 前端界面 (端口 5173)

- **React 18 + TypeScript**：现代化前端框架
- **Zustand**：状态管理
- **Tailwind CSS**：样式框架
- **WebSocket 客户端**：实时通信

### 语音服务

- **SenseVoice (ASR)**：阿里语音识别，支持多语言、实时流式、情感识别
- **F5-TTS (TTS)**：零样本语音克隆、实时流式合成、情感 TTS

## 功能特性

### 核心能力

- **语音对话**：端到端语音交互，ASR → LLM → TTS 全流程
- **智能记忆**：长期记忆存储、语义搜索、自动归档遗忘机制
- **多模型支持**：Ollama 本地模型，可扩展支持 VLLM 等其他 LLM
- **工具生态**：MCP（Model Context Protocol）协议支持，内置多种工具
- **ACP 协议**：局域网自动发现、点对点通信、群组协同
- **弹幕系统**：B站/RDF 弹幕接入，三档防火墙（block/passive/reply）
- **双向全双工**：支持用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**：WebRTC/Energy/Silero 多种模式

## 目录结构

```
CX-O/
├── CXHMS/                    # CXHMS 后端服务
│   ├── backend/
│   │   ├── api/routers/     # API 路由
│   │   │   ├── chat.py       # 聊天接口
│   │   │   ├── memory.py     # 记忆管理
│   │   │   ├── agents.py     # Agent 管理
│   │   │   ├── tools.py      # 工具管理
│   │   │   ├── acp.py        # ACP 协议
│   │   │   └── ...
│   │   ├── core/             # 核心模块
│   │   │   ├── memory/       # 记忆系统
│   │   │   ├── llm/          # LLM 客户端
│   │   │   ├── tools/        # 工具系统
│   │   │   ├── acp/          # ACP 协议
│   │   │   └── context/      # 上下文管理
│   │   └── tests/            # 测试用例
│   ├── config/               # 配置文件
│   ├── docs/                 # 服务文档
│   └── requirements.txt
│
├── cx-o-gateway/             # CX-O 网关服务
│   ├── gateway/              # WebSocket 网关
│   │   ├── server.py         # 主服务器
│   │   └── config.py         # 配置管理
│   ├── handlers/             # 消息处理器
│   │   ├── chat.py          # 聊天处理
│   │   ├── audio.py         # 音频处理
│   │   └── ...
│   ├── services/             # 服务层
│   │   ├── cxhms_client.py  # CXHMS 客户端
│   │   ├── tts_client.py    # TTS 客户端
│   │   ├── asr_client.py    # ASR 客户端
│   │   └── ...
│   └── requirements.txt
│
├── cx-o-frontend/            # CX-O 前端界面
│   └── src/
│       ├── api/             # API 客户端
│       ├── components/       # UI 组件
│       ├── pages/           # 页面
│       └── store/           # 状态管理
│
├── SenseVoice/               # 语音识别服务
├── F5-TTS/                  # 语音合成服务
├── CosyVoice/               # 备用语音合成
├── F5-fast/                 # F5-TTS 快速推理
│
├── docs/                    # 项目文档
│   ├── PROJECT_OVERVIEW.md  # 项目概述
│   ├── ARCHITECTURE.md      # 架构文档
│   ├── API.md               # API 文档
│   └── DEPLOYMENT.md        # 部署指南
│
└── data/                    # 共享数据
    ├── acp/                # ACP 配置
    ├── memories.db          # 记忆数据库
    └── sessions.db          # 会话数据库
```

## 服务端口

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CXHMS Backend | 8000 | HTTP | 核心 AI 服务 |
| CX-O Gateway | 8100 | WebSocket/HTTP | 统一入口 |
| CX-O Frontend | 5173 | HTTP | Web 前端 |
| SenseVoice ASR | 8001 | HTTP | 语音识别 |
| F5-TTS TTS | 8002 | HTTP | 语音合成 |
| CosyVoice | 8090 | HTTP | 备用语音合成 |

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
.\1-1.start-all.bat
```

#### 手动启动

1. **启动 CXHMS 后端**
```batch
cd CXHMS
python main.py
```

2. **启动 Gateway**
```batch
cd cx-o-gateway
python main.py
```

3. **启动前端**
```batch
cd cx-o-frontend
npm run dev
```

### 访问界面

- 前端界面: http://127.0.0.1:5173
- CXHMS API 文档: http://127.0.0.1:8000/docs
- CXHMS WebUI: http://127.0.0.1:7860

## 技术栈

### 后端

- **框架**: Python 3.10+, FastAPI, uvicorn
- **WebSocket**: fastapi-websocket
- **数据库**: SQLite, Milvus Lite, ChromaDB
- **LLM**: Ollama, VLLM
- **日志**: logging-config

### 前端

- **框架**: React 18+, TypeScript
- **状态管理**: Zustand
- **样式**: Tailwind CSS
- **构建工具**: Vite

### 语音模型

- **ASR**: SenseVoice（阿里，直接调用）
- **TTS**: F5-TTS（零样本语音克隆）
- **LLM**: Ollama（本地方便）、VLLM（高性能推理）

## WebSocket 协议

### 消息格式

```json
{
  "type": "request",
  "action": "module.action",
  "request_id": "uuid-string",
  "data": {}
}
```

### 核心 Action

| 模块 | Action | 说明 |
|------|--------|------|
| 聊天 | chat.message | 发送消息 |
| 聊天 | chat.stream | 流式聊天 |
| 记忆 | memory.list | 列出记忆 |
| 记忆 | memory.create | 创建记忆 |
| 记忆 | memory.search | 搜索记忆 |
| 工具 | tools.list | 列出工具 |
| 工具 | tools.call | 调用工具 |
| 语音 | asr.recognize | 语音识别 |
| 语音 | tts.synthesize | 语音合成 |

## 文档

- [架构文档](ARCHITECTURE.md)
- [API 文档](API.md)
- [部署指南](DEPLOYMENT.md)
- [CXHMS 文档](CXHMS.md)
- [网关文档](GATEWAY.md)
- [语音服务文档](VOICE_SERVICES.md)

## License

MIT
