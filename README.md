# CX-O 智能语音对话系统

基于单体架构的智能语音对话系统，集成语音识别（ASR）、大语言模型（LLM）和语音合成（TTS）能力，支持双向全双工语音交互。

## 系统架构

### v4 单体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Frontend                               │
│                   (React + TypeScript)                          │
│                      http://127.0.0.1:5173                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      CX-O Server (8100)                         │
│                   (单体应用，所有功能集成)                         │
│                                                               │
│   ┌─────────────────────────────────────────────────────────┐ │
│   │  Gateway Layer: WebSocket 处理、协议解析                   │ │
│   ├─────────────────────────────────────────────────────────┤ │
│   │  Services Layer: ASR/TTS 直接调用                        │ │
│   ├─────────────────────────────────────────────────────────┤ │
│   │  Core Layer: LLM/Memory/Tools/ACP                       │ │
│   └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**优势**：无网络开销，延迟降低 50%

## 功能特性

- **语音对话**：端到端语音交互，集成 ASR → LLM → TTS
- **智能记忆**：长期记忆存储、语义搜索、自动遗忘衰减机制
- **多模型支持**：Ollama 本地模型，可扩展支持 VLLM 等其他 LLM
- **工具生态**：MCP 协议支持，内置多种工具
- **ACP 协议**：局域网自动发现、点对点通信、群组协同
- **弹幕系统**：B站/RDF 弹幕接入，三档防火墙（block/passive/reply）
- **双向全双工**：支持用户打断 Agent TTS、Agent 打断用户说话
- **VAD 语音检测**：WebRTC/Energy/Silero 多种模式
- **情感 TTS**：支持多种情感音色的语音合成

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- Miniconda3 (项目内置)

### 启动服务

```batch
cd cx-o/server
python main.py
```

### 访问界面

- 管理控制台: http://127.0.0.1:5173

## 服务端口

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| CX-O Server | 8100 | WebSocket/HTTP | 单体应用，统一入口 |

## 项目结构

```
CX-O/
├── server/                    # 单体应用
│   ├── main.py               # 入口文件
│   ├── config.py             # 配置管理
│   ├── config.json           # 配置文件
│   │
│   ├── gateway/              # WebSocket 网关
│   │   ├── server.py         # 连接管理
│   │   └── health.py          # 健康检查
│   │
│   ├── handlers/             # 消息处理器
│   │   ├── chat.py           # 聊天消息处理
│   │   ├── memory.py         # 记忆管理
│   │   ├── audio.py          # 音频处理（ASR/TTS）
│   │   ├── live.py           # 直播客户端处理
│   │   ├── acp.py           # ACP 协议通信
│   │   └── mcp.py           # MCP 服务器管理
│   │
│   ├── services/             # 服务层（直接调用）
│   │   ├── asr.py            # SenseVoice ASR
│   │   ├── tts.py            # F5-TTS TTS
│   │   ├── emotion.py        # 情感解析
│   │   ├── effect.py         # 音效解析
│   │   ├── vad.py            # VAD 语音检测
│   │   ├── firewall.py       # 弹幕防火墙
│   │   └── interrupt.py      # 打断管理
│   │
│   ├── core/                 # 核心业务层
│   │   ├── llm/              # LLM 客户端
│   │   ├── memory/           # 记忆系统
│   │   ├── context/          # 上下文管理
│   │   ├── tools/            # 工具系统
│   │   ├── acp/              # ACP 协议
│   │   └── ...
│   │
│   ├── api/                  # REST API
│   │   ├── app.py            # FastAPI 应用
│   │   └── routers/          # 路由模块
│   │
│   └── protocol/              # 协议定义
│       ├── message.py         # 消息格式
│       └── actions.py         # Action 常量
│
├── frontend/                  # 前端管理界面
│   └── src/
│       ├── api/              # WebSocket 客户端
│       ├── components/       # UI 组件
│       ├── pages/            # 页面
│       └── store/            # 状态管理 (Zustand)
│
└── data/                      # 数据配置
    ├── acp/                  # ACP 配置
    └── memories.db            # 记忆数据库
```

## 配置说明

### 单体配置

文件: `server/config.json`

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8100
  },
  "asr": {
    "model_dir": "SenseVoice",
    "device": "cuda",
    "enabled": true
  },
  "tts": {
    "model_dir": "F5-TTS",
    "device": "cuda",
    "enabled": true,
    "ref_audio": "data/voice_refs/default.wav",
    "ref_text": "你好，我是语音助手。"
  },
  "llm": {
    "provider": "ollama",
    "host": "http://localhost:11434",
    "model": "qwen3-vl:8b"
  }
}
```

## WebSocket 协议

### 消息格式

```json
{
  "type": "request",
  "action": "chat.message",
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
| 语音 | asr.stream | 实时音频流（带 VAD） |

## v4 单体架构优势

### 延迟对比

| 架构 | ASR → LLM → TTS 延迟 |
|------|---------------------|
| 微服务 (v3) | ~800ms |
| 单体 (v4) | ~400ms |

### 资源对比

| 架构 | 内存占用 | 启动时间 |
|------|----------|----------|
| 微服务 (v3) | ~8GB | ~60s |
| 单体 (v4) | ~6GB | ~45s |

## 技术栈

- **网关**: Python, FastAPI, WebSocket, uvicorn
- **AI 服务**: SenseVoice (ASR), F5-TTS (TTS)
- **LLM**: Ollama, VLLM
- **数据库**: SQLite, Milvus Lite
- **前端**: React, TypeScript, Tailwind CSS, Zustand
- **协议**: MCP（Model Context Protocol）, ACP

## 开发

### 启动单体服务

```bash
cd cx-o/server
pip install -r requirements.txt
python main.py
```

### 前端开发

```bash
cd frontend
npm run dev
npm run build
npm run typecheck
```

## 文档

- [架构文档](docs/ARCHITECTURE.md)
- [项目概述](docs/PROJECT_OVERVIEW.md)
- [API 文档](docs/API.md)
- [部署指南](docs/DEPLOYMENT.md)

## License

MIT
